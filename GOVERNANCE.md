# Governance

AEC Model Bridge is a one-person project today. A. Sam Mohammad ([@Sam-AEC](https://github.com/Sam-AEC)) is the only maintainer. There is no steering committee, foundation or company board behind it.

This page says how that works in practice, so contributors know what to expect.

## Roles

- **Maintainer.** Reviews and merges pull requests, cuts releases, and owns the licence and the name. Today that is one person.
- **Contributor.** Anyone who opens an issue, sends a pull request, improves docs or reviews a translation. Accepted contributors are credited in [CONTRIBUTORS.md](CONTRIBUTORS.md).

## How decisions are made

The maintainer decides. For anything beyond a small fix, the process is:

1. Open an issue and describe the problem. For code, do this before you write it. [CONTRIBUTING.md](CONTRIBUTING.md) explains why.
2. Talk it through in the issue. Larger design choices are written up as numbered notes in `docs/` (for example [the approval gate lifecycle](docs/0008-approval-gate-lifecycle.md)).
3. The maintainer decides and says why. Disagreement is welcome and is heard, but the maintainer has the final say.

Releases follow [docs/versioning.md](docs/versioning.md). Removals follow [docs/deprecation-policy.md](docs/deprecation-policy.md).

With one maintainer, there is no second reviewer. CI must pass, and the maintainer reads every change. Branch protection can require a second human review once there is a second person able to give one.

## Licence and name

The code is under GPL-3.0-or-later with the Revit Linking Exception, and there is a separate commercial licence. See [LICENSING.md](LICENSING.md). Code pull requests need a contributor agreement so that both options stay possible. The name and logo are covered by [TRADEMARKS.md](TRADEMARKS.md).

## Becoming a maintainer

There is no fixed ladder. In practice, a person might be asked to become a maintainer after they have:

- sent several accepted, well-tested changes over a period of months
- reviewed other people's work with care
- shown good judgement on security-sensitive code
- followed the [Code of Conduct](CODE_OF_CONDUCT.md)

The maintainer chooses. A new maintainer must sign the contributor agreement and would be added to [.github/CODEOWNERS](.github/CODEOWNERS). If you are interested, open an issue or write to the address in the Code of Conduct. Do not expect a quick answer.

## Disputes and conduct

- **Technical disagreements.** Make your case in the issue. The maintainer decides.
- **Conduct problems.** Follow [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md). Reports go to the maintainer, who handles them in confidence. This means a complaint about the maintainer has no independent reviewer today. If that is your situation, say so in your report. The project cannot promise a neutral third party yet.
- **Security.** Do not use public channels. Follow [SECURITY.md](SECURITY.md).

## If the maintainer stops

A single maintainer is a risk. The code is public and under the GPL, so anyone can fork it without asking.

## Changing this page

Changes to this page are made in a pull request, so the history is visible. If the project gains more maintainers, this page should be rewritten to match.
