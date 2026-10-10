# Support

AEC Model Bridge is maintained by one person, in their own time. This page says where to ask and what to expect.

## Where to ask

| You want to | Go here |
|---|---|
| Report a bug | [Open a bug report](https://github.com/Sam-AEC/aec-model-bridge/issues/new?template=bug_report.yml) |
| Suggest a feature | [Open a feature request](https://github.com/Sam-AEC/aec-model-bridge/issues/new?template=feature_request.yml) |
| Report a security problem | Use [private reporting](https://github.com/Sam-AEC/aec-model-bridge/security/advisories/new). Read [SECURITY.md](SECURITY.md) first. Do not open a public issue. |
| Report unacceptable behaviour | See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) |
| Ask about licensing or a commercial licence | Read [LICENSING.md](LICENSING.md) |
| Ask about the name or logo | Read [TRADEMARKS.md](TRADEMARKS.md) |
| Fix or improve something yourself | Read [CONTRIBUTING.md](CONTRIBUTING.md) |

Before you open an issue, search the existing ones. Check [docs/install.md](docs/install.md) and [docs/compatibility.md](docs/compatibility.md) too.

## What to include

A good report lets someone else repeat the problem. Please give:

- the AEC Model Bridge version (the `VERSION` file, or the installer or release name)
- your Revit year, or say that you used mock mode (`MCP_REVIT_MODE=mock`)
- your Windows version and Python version
- the AI client you used (Claude Desktop, VS Code, Cursor, Codex, or other)
- the steps you took, what you expected and what happened
- the relevant lines from the audit log, `%APPDATA%\AECModelBridge\Logs\bridge.jsonl`

Remove model names, file paths, server names and credentials you do not want public. Never paste secrets.

## What is supported

- Revit 2024 to 2027. See [docs/target-frameworks-and-dependencies.md](docs/target-frameworks-and-dependencies.md).
- Python 3.11 to 3.13.
- The latest release. See the table in [SECURITY.md](SECURITY.md#supported-versions) and [docs/deprecation-policy.md](docs/deprecation-policy.md).

## What is not supported

- **Live Revit on anything but Windows.** Revit runs only on Windows, so the add-in does too. On Linux and macOS you can run the server in mock mode and read the code. The Linux CI job is experimental.
- **Clients that have not been tested.** [docs/compatibility.md](docs/compatibility.md) lists which clients are documented and which are not tested. Reports from other clients are welcome, but fixing them is best effort.
- **Navisworks and Power BI.** The compatibility page marks both as in progress.
- **Revit versions before 2024 or after 2027.**
- **Help with your own Revit models, templates or standards.** Please ask a colleague or a Revit forum for that.
- **Releases that are not the latest**, apart from what [SECURITY.md](SECURITY.md) says.
- **Custom forks and modified builds.**

## What to expect

There is no support contract, no service level and no promised response time. One maintainer reads issues when time allows. That can mean days, and sometimes weeks.

For security reports, [SECURITY.md](SECURITY.md) states the targets the project aims for. Those are goals for one person, not a guarantee.

Issues that are clear, small and repeatable get looked at first. Reports with no version, no steps or no log may be closed with a request for more detail.

If you need guaranteed help, see the commercial licence option in [LICENSING.md](LICENSING.md).
