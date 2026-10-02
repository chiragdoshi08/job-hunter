from hunter import db,identities

def fixture_masters():
    with db.tx() as c:
        for i in db.DEFAULT_IDENTITIES:c.execute('UPDATE identities SET master_id=? WHERE id=?',('fixture-master-'+i,i))
    identities.refresh()
