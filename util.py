
def has_config(wallet, key: str):
	key = "chaintipper_" + key
	if wallet.storage.get(key) is None: 
		return False
	return len(wallet.storage.get(key)) > 0

def read_config(wallet, key: str, default=None, commit=True):
	"""convenience function to write to wallet storage prefixing key with 'chaintipper_'"""
	key = "chaintipper_" + key
	v = wallet.storage.get(key)
	if v is None:
		v = default
		write_config(wallet, key, v, commit)
	return v

def write_config(wallet, key: str, value, commit=True):
	"""convenience to read from wallet storage prefixing key with 'chaintipper_'"""
	if key[:12] != "chaintipper_":
		key = "chaintipper_" + key
	wallet.storage.put(key, value)
	if commit:
		wallet.storage._write() # commit to hd

def commit_config(wallet):
	wallet.storage.write() # commit to hd
