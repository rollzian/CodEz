package main

import (
	"context"
	"errors"
	"fmt"
	"os"
	"os/signal"
	"strconv"
	"strings"
	"time"

	"github.com/AuxiaCorp/CodEz/internal/auxia"
	"github.com/AuxiaCorp/CodEz/internal/config"
)

func (c console) auxiaHub(section string) error {
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt)
	defer stop()
	token, e := config.AuxiaToken()
	if e != nil && !os.IsNotExist(e) {
		return e
	}
	if token == "" {
		subtitle := "Cloud collaboration · separate from your AI provider"
		if section != "" {
			subtitle = map[string]string{"workspaces": "Workspaces", "teams": "Teams", "friends": "Friends", "projects": "Public Projects"}[section] + " · " + subtitle
		}
		choice, e := c.selectMenu("Auxia / Connect", subtitle, []string{"Sign in with Auxia account", "Back"}, false)
		if e != nil || choice != "1" {
			return e
		}
		token, e = auxia.New("").Login(ctx, func(d auxia.Device) {
			c.section("Verify this device")
			fmt.Fprintln(c.out, "  "+c.style("1;"+accent, d.UserCode))
			c.browser(d.VerificationURI)
			c.note("Approve the matching code in your browser. Ctrl+C cancels.")
		})
		if e != nil {
			return e
		}
		if e = config.SaveAuxiaToken(token); e != nil {
			return e
		}
	}
	client := auxia.New(token)
	for {
		profile, e := client.Me(ctx)
		if e != nil {
			var f *auxia.Failure
			if errors.As(e, &f) && f.Status == 401 {
				_ = config.RemoveAuxiaToken()
				return errors.New("Auxia session expired. Reopen /auxia to sign in")
			}
			return e
		}
		if section != "" {
			if e := c.auxiaCollection(ctx, client, section, profile); e != nil {
				return e
			}
			return nil
		}
		choice, e := c.selectMenu("Auxia / Home", profile.Name+"  ·  ID "+profile.ID, []string{"Workspaces     /  Organize your projects", "Teams          /  Collaborate with members", "Friends        /  Connect with developers", "Public Projects /  Discover and publish", "Sign out", "Back to agent"}, false)
		if e != nil {
			return e
		}
		switch choice {
		case "1", "2", "3", "4":
			n, _ := strconv.Atoi(choice)
			if e = c.auxiaCollection(ctx, client, []string{"workspaces", "teams", "friends", "projects"}[n-1], profile); e != nil {
				c.failure(e.Error())
			}
		case "5":
			if e = client.Logout(ctx); e != nil {
				return e
			}
			return config.RemoveAuxiaToken()
		default:
			return nil
		}
	}
}
func (c console) auxiaCollection(ctx context.Context, client *auxia.Client, kind string, profile auxia.Profile) error {
	for {
		stop := c.progress("Loading " + kind)
		items, e := client.List(ctx, kind)
		stop()
		if e != nil {
			return e
		}
		labels := []string{map[string]string{"workspaces": "+ Create workspace", "teams": "+ Create team", "friends": "+ Send friend request", "projects": "+ Publish project"}[kind]}
		for _, x := range items {
			role := x.State
			if x.Role != "" {
				role = x.Role
				if x.State == "invited" {
					role += " (invited)"
				}
			}
			labels = append(labels, clean(x.Name+"  ·  "+x.Detail+"  ·  "+role))
		}
		labels = append(labels, "Back")
		choice, e := c.selectMenu("Auxia / "+strings.ToUpper(kind[:1])+kind[1:], fmt.Sprintf("%d items · %s", len(items), profile.Name), labels, false)
		if e != nil {
			return e
		}
		n, _ := strconv.Atoi(choice)
		if n < 1 || n > len(labels) || n == len(labels) {
			return nil
		}
		if n == 1 {
			fields := map[string]string{}
			if kind == "friends" {
				fields["user_id"], e = c.ask("  Auxia user ID: ")
			} else {
				fields["name"], e = c.ask("  Name: ")
			}
			if e != nil {
				return e
			}
			if kind == "workspaces" {
				teams, err := client.List(ctx, "teams")
				if err != nil {
					return err
				}
				names := []string{"Personal · private"}
				ids := []string{""}
				for _, team := range teams {
					if team.State == "owner" || team.State == "member" && (team.Role == "" || team.Role == "admin" || team.Role == "maintainer" || team.Role == "developer") {
						names = append(names, team.Name+" · team workspace")
						ids = append(ids, team.ID)
					}
				}
				v, err := c.selectMenu("Workspace visibility", "Choose who can access this workspace", names, false)
				if err != nil {
					return err
				}
				i, err := strconv.Atoi(v)
				if err != nil || i < 1 || i > len(ids) {
					return errors.New("invalid selection")
				}
				fields["team_id"] = ids[i-1]
			}
			if kind == "projects" {
				c.note("This publishes a public directory entry and repository link, not local files.")
				fields["url"], e = c.ask("  Public HTTPS repository URL: ")
				if e != nil {
					return e
				}
			}
			if e = client.Create(ctx, kind, fields); e != nil {
				c.failure(e.Error())
			} else {
				c.success("Saved")
			}
			continue
		}
		x := items[n-2]
		c.section(clean(x.Name))
		c.note("ID: " + x.ID)
		if x.URL != "" {
			c.note(x.URL)
		}
		options := []string{}
		actions := []string{}
		if x.State == "invited" || x.State == "incoming" {
			options = append(options, "Accept invitation")
			actions = append(actions, "accept")
		}
		if kind == "teams" && (x.State == "owner" || x.State == "member" && x.Role != "guest") {
			options = append(options, "View members")
			actions = append(actions, "members")
		}
		if kind == "teams" && (x.State == "owner" || x.State == "member" && x.Role == "admin") {
			options = append(options, "Invite member", "Remove member")
			actions = append(actions, "invite", "remove_member")
		}
		if kind == "teams" && x.State == "owner" {
			options = append(options, "Change member role")
			actions = append(actions, "role")
		}
		if kind == "teams" && (x.State == "member" || x.State == "invited") {
			options = append(options, "Leave / decline team")
			actions = append(actions, "leave")
		}
		if x.State == "owner" || kind == "friends" {
			options = append(options, "Remove")
			actions = append(actions, "delete")
		}
		if kind == "projects" && x.URL != "" {
			options = append(options, "Open repository")
			actions = append(actions, "open")
		}
		options = append(options, "Back")
		choice, e = c.selectMenu("Auxia / "+x.Name, x.Detail, options, false)
		if e != nil {
			return e
		}
		i, _ := strconv.Atoi(choice)
		if i < 1 || i > len(actions) {
			continue
		}
		act := actions[i-1]
		if act == "members" {
			members, err := client.TeamMembers(ctx, x.ID)
			if err != nil {
				c.failure(err.Error())
				continue
			}
			c.section("Team members")
			for _, m := range members {
				role := m.Role
				if role == "" {
					role = m.State
				}
				c.note(m.Name + " · " + role + " · " + m.ID)
			}
			_, err = c.ask("  Enter to return: ")
			if err != nil {
				return err
			}
			continue
		}
		if act == "open" {
			c.browser(x.URL)
			continue
		}
		fields := map[string]string{}
		if act == "invite" || act == "role" || act == "remove_member" {
			fields["user_id"], e = c.ask("  Auxia user ID: ")
			if e != nil {
				return e
			}
		}
		if act == "role" {
			roles := []string{"admin", "maintainer", "developer", "reviewer", "viewer", "guest"}
			choice, err := c.selectMenu("Member role", "Choose the new team role", roles, false)
			if err != nil {
				continue
			}
			n, err := strconv.Atoi(choice)
			if err != nil || n < 1 || n > len(roles) {
				continue
			}
			fields["role"] = roles[n-1]
		}
		if act == "delete" || act == "leave" || act == "remove_member" {
			v, e := c.ask("  Remove this item? [y/N]: ")
			if e != nil {
				return e
			}
			if !strings.EqualFold(v, "y") {
				continue
			}
		}
		op, cancel := context.WithTimeout(ctx, 20*time.Second)
		e = client.Action(op, kind, x.ID, act, fields)
		cancel()
		if e != nil {
			c.failure(e.Error())
		} else {
			c.success("Updated")
		}
	}
}
