
def read_config(wallet, key: str, default=None):
	"""convenience function to write to wallet storage prefixing key with 'chaintipper_'"""
	key = "chaintipper_" + key
	v = wallet.storage.get(key)
	if v is None:
		v = default
		write_config(wallet, key, v)
	return v

def write_config(wallet, key: str, value):
	"""convenience to read from wallet storage prefixing key with 'chaintipper_'"""
	key = "chaintipper_" + key
	wallet.storage.put(key, value)