from .config import c

def has_config(wallet, key: str):
	key = "chaintipper_" + key
	if wallet.storage.get(key) is None: 
		return False
	return len(wallet.storage.get(key)) > 0

def read_config(wallet, key: str, default=None):
	"""convenience function to write to wallet storage prefixing key with 'chaintipper_'"""
	v = wallet.storage.get("chaintipper_" + key)
	if v is None:
		if default is None:
			default = c['default_' + key]
			if default is None:
				raise Exception("no default value found in config for key default_" + key)
		v = default
		write_config(wallet, key, v)
	return v

def write_config(wallet, key: str, value):
	"""convenience to read from wallet storage prefixing key with 'chaintipper_'"""
	if key[:12] != "chaintipper_":
		key = "chaintipper_" + key
	wallet.storage.put(key, value)

def commit_config(wallet):
	wallet.storage.write() # commit to hd
