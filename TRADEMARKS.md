# Trademark and API Use

AEC Model Bridge is an independent software project maintained by Sam-AEC. It
is not affiliated with, sponsored by, endorsed by, or provided by Autodesk.

Autodesk and Revit are trademarks of the Autodesk group of companies. Other
product and company names may be trademarks of their respective owners.

References to Autodesk Revit software describe compatibility only. They are
not part of the AEC Model Bridge product name.

## The Project Name and Logo

"AEC Model Bridge" is the name of this project, and the Pier mark (the logo
in `assets/`) is its logo. The software licences in [LICENSING.md](LICENSING.md)
cover the code. They do not give you the right to use the name or the logo
as your own.

You do not need to ask for permission to:

- say that your product, script or article works with AEC Model Bridge, or is
  compatible with it, as long as it is clear that yours is a separate thing;
- redistribute unmodified copies of the software, with its licence files, and
  call it by its name;
- write about the project, review it, or link to it, including with the name
  and logo in a plain, unaltered form.

Please ask first if you want to:

- suggest that your product, service or company is made, endorsed or
  certified by the AEC Model Bridge project or its maintainer;
- sell or distribute a modified version, or a competing product or service,
  under the name "AEC Model Bridge" or with a name or logo that could be
  confused with it (use your own name and say that it is based on this
  project); or
- use the logo in a changed form, or as part of your own logo.

To ask, open an issue at
<https://github.com/Sam-AEC/aec-model-bridge/issues>. This policy does not claim
a registered trademark.

The authorship record for the Pier mark is not written down in the
repository yet. This section will be updated when it is.

## Technical Boundary

AEC Model Bridge:

- uses the documented Revit desktop .NET API;
- requires users to provide their own properly licensed Autodesk software;
- does not distribute `RevitAPI.dll`, `RevitAPIUI.dll`, Autodesk product
  icons, Autodesk logos, or Autodesk application binaries;
- does not claim Autodesk certification, sponsorship, or endorsement; and
- does not use undocumented API calls intentionally.

The release build checks packaged files for known Autodesk API assemblies and
fails if they are present.

The project licenses apply only to code and assets the applicable licensors
have the right to license. They do not grant rights to Autodesk trademarks,
software, APIs, or other third-party intellectual property. See
[LICENSING.md](LICENSING.md) for the version-specific software terms.

Users are responsible for complying with the license terms that apply to their
Autodesk installation. Autodesk Education licenses must not be used for
commercial work.

This notice describes the project's compliance approach and is not legal
advice. Commercial distribution should receive independent trademark and
software-licensing review.
