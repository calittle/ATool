# Bundled software

ATool includes Python, Qt/PySide6 (including Qt WebEngine and Chromium), Node.js,
and OCCS CLI with its locked npm dependencies. Runtime versions and the exact
ATool/OCCS CLI commits are recorded in RUNTIME_INFO.json inside the bundle.

ATool and OCCS CLI are distributed under GPL version 3; their license texts are
included here. Corresponding application source is available at
https://github.com/calittle/ATool and https://github.com/calittle/OCCS-CLI,
at the commits in RUNTIME_INFO.json. npm package license files are retained
inside runtime/occs-cli/node_modules.

Node.js and its dependency notices are in Node-LICENSE.txt.
Python's license is included as Python-LICENSE.txt;
Python source is at https://www.python.org/downloads/source/.
Qt/PySide6 license information and corresponding source are available at
https://doc.qt.io/qtforpython-6/licenses.html and
https://download.qt.io/official_releases/qt/.
The LGPL version 3 text is included as Qt-LGPL-3.0.txt.
Chromium notices are also accessible through Qt WebEngine's qt://credits page.

The distribution retains separate runtime libraries so the bundled Qt libraries
can be replaced. No OCCS credentials, tokens, session files, or customer data
are included. OCCS authentication is configured by the user after installation.
