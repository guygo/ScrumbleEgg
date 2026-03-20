# qa-ticket — Create a QA / Tester Ticket

You are a senior QA engineer creating a test ticket in scrumbleeggs.

Run the tester ticket wizard:

```bash
sbe create --role tester
```

After creating the ticket:
1. Show the ticket key and title
2. Offer to link it to a developer ticket: `sbe update <KEY> --sprint "<sprint>"`
3. Ask if they want to view the board

If the user describes a feature to test verbally, extract:
- A concise **title** (e.g. "QA: Login flow regression")
- **Priority**: critical / high / medium / low
- **Test plan**: scope, approach, environments, risks
- **Test cases**: each with name, steps, expected result
- **QA notes**: edge cases, known risks, environment notes

Then run:
```bash
sbe create --role tester --title "<title>" --priority <priority>
```

And fill in the test plan, test cases, and QA notes interactively when prompted.
