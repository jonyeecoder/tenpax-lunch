# Plan: Tenpax lunch runs

## Who and what
Ten coworkers who order lunch together most workdays. One person "does the run": picks a place, collects everyone's order, places it, then collects money.

## Problem statement (4Cs)
Assumptions are marked *(check)*. Replace them with real numbers after a week of watching.

- **Clarity:** Lunch orders are collected in the group chat. People reply between other messages, change their minds, or forget to reply. Whoever does the run has to scroll back and rebuild the list by hand.
- **Consequence:** Orders get missed or come out wrong. The orderer loses about 15 minutes a day *(check)* and is out of pocket when people forget to pay *(check)*. The same one or two people end up doing it every time.
- **Cause:** A chat is built for conversation, not for collecting a list. Nothing shows in one place what each person ordered and whether they've paid.
- **Confirmation:** *To collect over one week:* minutes spent compiling orders, number of missed or wrong orders, and money still owed at the end of the week.

## Success metric (SMART)
**By the end of week 2, at least 8 of the 10 coworkers place their order in the app on 3 or more days a week.**
This is a leading indicator. The lagging one is that the orderer's time per run drops from about 15 minutes to under 3 by the end of week 4.

## Riskiest assumption
People will leave the group chat and use an app for lunch at all. The first version exists to test only that.

## Skateboard (v1)
- Log in. Coworkers sign up with a shared team code, capped at 10 accounts.
- Start a lunch run: the place and an order cutoff time.
- Add or edit your order: the item and its price.
- The organizer sees the full list and total, ticks off who has paid, and closes the run.

## Not in v1
Voting on places, menus, payment integration, notifications, run history and stats.

## Stack
Python + Flask + SQLite (one file, no database server). Passwords are hashed with Werkzeug. Secrets live in `.env`, which is never committed.
