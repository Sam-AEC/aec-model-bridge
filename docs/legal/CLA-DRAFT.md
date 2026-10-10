# DRAFT: not reviewed by a lawyer, not in force

This file is a draft for discussion. No lawyer has reviewed it. It is **not in
force**: nobody has signed it, the project does not accept contributions under
it today, and nothing in it changes the terms in [LICENSING.md](../../LICENSING.md)
or [CONTRIBUTING.md](../../CONTRIBUTING.md). The wording below is a starting
point for a lawyer to rewrite. The project may adopt Option A, Option B, both,
or neither.

## Why a draft exists

AEC Model Bridge is offered under GPL-3.0-or-later with the Revit Linking
Exception, and also under a commercial licence. To keep offering both, the
maintainer needs the right to license each contribution under both. Today there
is no signed contributor agreement and no sign-off rule, so outside code
cannot be taken on that basis.

## Option A: Individual Contributor Licence Agreement (draft)

"You" is the person who signs. "Maintainer" is A. Sam Mohammad, or any
successor or company that takes over the project. "Contribution" is any code,
documentation or other work you submit to the project.

1. **Your rights.** You confirm that you wrote the Contribution, or that you
   have the right to submit it under this agreement. If your employer or
   another party has rights in it, you have their permission.
2. **Copyright licence.** You grant the Maintainer a perpetual, worldwide,
   non-exclusive, royalty-free, irrevocable licence to use, copy, modify,
   publish, distribute and sublicense your Contribution, and derivative works
   of it, under any licence terms, including open-source and commercial
   (proprietary) terms. You keep your copyright.
3. **Patent licence.** You grant the Maintainer and recipients of the project a
   perpetual, worldwide, non-exclusive, royalty-free, irrevocable patent
   licence for patent claims you own that are necessarily infringed by your
   Contribution alone or combined with the project.
4. **Open-source licence stays available.** The Maintainer will keep making the
   project available under GPL-3.0-or-later (with the Revit Linking Exception)
   for as long as it makes the project available at all. [Open question for a
   lawyer: whether and how to state this commitment.]
5. **No third-party code you cannot license.** You will not submit code that is
   licensed only under terms that stop the Maintainer from using item 2, such
   as GPL-only code copied from another project. If your Contribution includes
   third-party code, you will say so and name its licence.
6. **No warranty.** Your Contribution is provided as is, without warranty.
7. **Notice.** You will tell the Maintainer if you learn that any statement
   above was untrue.

Signature: name, GitHub handle, date, and a statement "I agree to the
Individual Contributor Licence Agreement."

## Option B: Developer Certificate of Origin (DCO) plus a licence grant

Contributors add a `Signed-off-by: Name <email>` line to each commit
(`git commit -s`). By doing so, they certify the Developer Certificate of
Origin, version 1.1 (<https://developercertificate.org>), whose text is
maintained by the Linux Foundation and should be copied here verbatim if this
option is adopted.

The DCO says that you may submit the work under the project's licence. By
itself it does not allow the Maintainer to relicense under a different,
commercial licence. To cover that, this option adds the following sentence to
the contributing rules:

> By signing off a commit, you also grant the Maintainer the licence in
> items 2 and 3 of the Individual Contributor Licence Agreement
> (docs/legal/CLA-DRAFT.md).

## What a lawyer should decide

- Whether Option A, B or both are enforceable and sufficient for the planned
  dual licensing, in the countries that matter.
- How to handle contributors who are employees, and companies that contribute.
- How to treat the earlier contributions made while the project was
  MIT-licensed (see [CONTRIBUTORS.md](../../CONTRIBUTORS.md)).
- Whether the "open-source licence stays available" promise in item 4 should
  be binding, and in what words.
- Whether AI-assisted contributions need an extra statement.
