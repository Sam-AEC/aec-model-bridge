# GitHub Discussions setup

Discussions hold questions, ideas and shared work. Bugs and feature requests stay in issues. Only a repository admin can enable Discussions and create categories.

## Enable

1. Repository Settings, General, Features: tick Discussions.
2. Open the Discussions tab, then Categories (the pencil icon next to the category list).
3. Make the categories below. GitHub creates some by default; rename or delete the others (General, Polls) so only these four remain.
4. Pin the welcome post below in Announcements.

## Categories

| Category | Slug | Format | Who can post | Form |
|---|---|---|---|---|
| Announcements | `announcements` | Announcement | Maintainers only | None |
| Q&A | `q-a` | Question and answer | Everyone | `.github/DISCUSSION_TEMPLATE/q-a.yml` |
| Ideas | `ideas` | Open-ended discussion | Everyone | `.github/DISCUSSION_TEMPLATE/ideas.yml` |
| Show and tell | `show-and-tell` | Open-ended discussion | Everyone | `.github/DISCUSSION_TEMPLATE/show-and-tell.yml` |

GitHub matches a form to a category by file name, so the slug must equal the file name without `.yml`. Check the slug in the category's URL after creating it. A form whose name matches no category is ignored.

Suggested descriptions:

- Announcements: Releases and changes that need action from users.
- Q&A: How to install, configure and use AEC Model Bridge.
- Ideas: Workflows and tools you would like to see, before they become feature requests.
- Show and tell: Workflows, prompts, rule packs and modules you built.

## Links

`.github/ISSUE_TEMPLATE/config.yml` links to Discussions from the new-issue page. The link returns 404 until Discussions is enabled.

## Welcome post

Post in Announcements and pin it.

Title: `Welcome to AEC Model Bridge Discussions`

```markdown
This is the place for questions, ideas and work you want to share about AEC Model Bridge, the open-source Revit MCP server.

- Q&A: ask how to install, configure or use it. Mark the answer that solved it.
- Ideas: describe a workflow or tool you would like. Clear ideas move to a feature request.
- Show and tell: share prompts, rule packs, modules and results.

Before you post:

- Bugs go in a bug report issue, not here.
- Security problems go through private reporting (Security tab, Report a vulnerability). Never post them in public.
- Remove model names, file paths and credentials you do not want public.
- You can try the tools without Revit: set MCP_REVIT_MODE=mock. Live use needs Windows, Revit 2024 to 2027 and the add-in.

Answers come from the maintainer and other users in their own time. See SUPPORT.md for what is supported.
```
