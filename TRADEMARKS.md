# Trademark and API Use

AEC Model Bridge is an independent software project maintained by Sam-AEC. It
is not affiliated with, sponsored by, endorsed by, or provided by Autodesk.

Autodesk and Revit are trademarks of the Autodesk group of companies. Other
product and company names may be trademarks of their respective owners.

References to Autodesk Revit® software describe compatibility only. They are
not part of the AEC Model Bridge product name.

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

The MIT License applies only to this project's original code and assets. It
does not grant rights to Autodesk trademarks, software, or other third-party
intellectual property.

Users are responsible for complying with the license terms that apply to their
Autodesk installation. Autodesk Education licenses must not be used for
commercial work.

This notice describes the project's compliance approach and is not legal
advice. Commercial distribution should receive independent trademark and
software-licensing review.
