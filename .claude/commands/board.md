# board — View the Scrum Board

Display the full scrum board:

```bash
sbe board
```

Or filter by sprint:

```bash
sbe board --sprint "Sprint 1"
```

After showing the board, offer these follow-up actions:
- Move a ticket: `sbe move <KEY> <status>`
- Show ticket detail: `sbe show <KEY>`
- Export board as markdown: `sbe export --format markdown --sprint "<sprint>"`
- List tickets with filters: `sbe list --status in_progress`
