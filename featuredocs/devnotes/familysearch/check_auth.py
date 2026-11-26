from gramps.gui.fs.manager import get_session
session = get_session()
if session:
    print(f"Logged in: {session.logged}")
    print(f"Auth provider: {session.auth_provider}")
    print(f"Can probe: {session.probe_api()}")
