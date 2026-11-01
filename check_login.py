import getpass

from musicapp import load_config
from navidrome import NavidromeClient

cfg = load_config()
print("Parsed config:", cfg)

client = NavidromeClient(cfg.url, cfg.user, getpass.getpass("Password: "))
print("Base URL used:", client.base_url)

client.ping()
print("Login OK")
print("Artists found:", len(client.artists()))