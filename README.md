# MEHDORA Textile Studio

MEHDORA Textile Studio is a Windows-focused textile design application based
on the Krita 6.0.3 source tree. This repository stores the MEHDORA patch stack
and an automated reproducible build workflow instead of duplicating the full
upstream source history.

## Build

Open **Actions → Build MEHDORA Windows → Run workflow**. The workflow:

1. downloads the exact Krita 6.0.3 source revision;
2. reconstructs and applies the nine MEHDORA patches;
3. verifies the MEHDORA name, icon, splash and Windows metadata;
4. builds the application and unsigned Windows installer;
5. uploads the installer and portable ZIP as workflow artifacts.

The build intentionally remains unsigned until a Windows code-signing
certificate is configured.

## License

MEHDORA Textile Studio is a modified Krita distribution and remains subject to
the GNU General Public License and the applicable third-party notices. Visible
application branding is MEHDORA; upstream copyright and license notices remain
available in the source distribution.
