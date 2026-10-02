#!/bin/zsh
cd "${0:A:h}"
print 'Stop Job Hunter before restoring. Existing state is kept as a safety copy.'
read 'hunter_backup?Drag a Job Hunter backup ZIP here, then press Enter: '
hunter_backup=${hunter_backup//\\/}
hunter_backup=${hunter_backup% }
.venv/bin/python -m hunter.cli restore --file "$hunter_backup"
read '?Press Enter to close…'
