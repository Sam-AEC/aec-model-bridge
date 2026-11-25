# Roadmap

Where the work is tracked:

- [Project board](https://github.com/users/Sam-AEC/projects/2): open issues and pull requests by status, priority, size, area and owner. Labels are the source of truth; see [docs/project-board.md](docs/project-board.md).
- [Milestone 1.6](https://github.com/Sam-AEC/aec-model-bridge/milestone/3): the current release.
- [Backlog milestone](https://github.com/Sam-AEC/aec-model-bridge/milestone/4): accepted work with no release date.
- [Tracking issues](https://github.com/Sam-AEC/aec-model-bridge/labels/type%3A%20tracking): one per theme (release readiness, AI and MCP connection, Revit-side speed, MCP protocol coverage, model QA and data exchange).
- [Discussions](https://github.com/Sam-AEC/aec-model-bridge/discussions): ideas and questions before they become issues.

## How an item moves

1. An idea starts in Discussions or as a feature request.
2. A maintainer labels it with a priority (P0 to P3), a size (S, M, L) and an area, and sets a milestone.
3. Work that needs a live Revit session carries `status: needs-live-verification`. It is not called done until that check passes, and the release notes mark it UNVERIFIED until then.
4. Work that needs admin access or a licensed Revit on the maintainer machine carries `status: maintainer-only`.
5. Pull requests target `dev`. `main` receives `dev` through a release pull request.

Good first issues carry `good first issue`; larger open items carry `help wanted`.
