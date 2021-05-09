from decimal import Decimal

c = {
		# reddit config
		"reddit": {
			"url_prefix": "http://reddit.com",
			"client_id": "i0POn9dIWWARlA", # registered by u/chaintipper
			"script_client_id": "tKD-V4boaPtP3g",
			"script_client_secret": "3puUGKKmHggUoan265M6GEOnPozBCw",
			"user_agent": "electroncash.chaintipper (by u/moleccc)",
			"redirect_uri": "https://localhost:18763",
			"local_auth_server_port": 18763
		},
		"use_categories": False,
		"default_amount": "0.1",
		"default_amount_currency": "USD",
		
		"default_autopay": False,
		"default_autopay_use_limit": False,
		"default_autopay_limit_bch": "0.01",
		"default_autopay_disallow_default": False,
		"default_autopay_disallow_linked": False,
}

amount_config = {
	"default_amount_bch": Decimal("0.00001337"),
	"units": [
		{ 
			"names": ["mbit","mbits"], 
			"value": Decimal("1"),
			"value_currency": "BCH",
		},
		{ 
			"names": ["kbit","kbits"], 
			"value": Decimal("0.001"),
			"value_currency": "BCH",
		},
		{ 
			"names": ["bit","bits","cash"], 
			"value": Decimal("0.000001"),
			"value_currency": "BCH",
		},
		{ 
			"names": ["sat","sats","satoshi","satoshis"], 
			"value": Decimal("0.00000001"),
			"value_currency": "BCH",
		},
		{ 
			"names": ["dust","dusts","spam","test","chaintip_minimum"],
			"value": Decimal("0.00001155"),
			"value_currency": "BCH"
		},
		{
			"names": ["bubblegum","bubblegums"],
			"value": Decimal("0.0717"),
			"value_currency": "EUR",
		},
		{
			"names": ["espresso", "espressi", "espressos", "cortado", "cortados","cafe","caffee","caffe"],
			"value": Decimal("1"),
			"value_currency": "EUR",
		},
		{
			"names": ["beer","beers","coffee","coffees"],
			"value": Decimal("3"),
			"value_currency": "EUR",
		},
		{
			"names": ["pizza", "pizzas","meal"],
			"value": Decimal("15"),
			"value_currency": "USD"
		},
		{ 
			"names": ["smile","smiles"],
			"value": Decimal("0.0001337"),
			"value_currency": "BCH"
		},
		{ 
			"names": ["leet", "leets"],
			"value": Decimal("0.01337"),
			"value_currency": "BCH"
		},
		{ 
			"names": ["dollar", "dollars"],
			"value": Decimal("1.0"),
			"value_currency": "USD"
		},
		{ 
			"names": ["quarter","quarters"],
			"value": Decimal("0.25"),
			"value_currency": "USD"
		},
		{ 
			"names": ["dime","dimes"],
			"value": Decimal("0.1"),
			"value_currency": "USD"
		},
		{ 
			"names": ["nickel","nickels"],
			"value": Decimal("0.05"),
			"value_currency": "USD"
		},
		{ 
			"names": ["cent","cents"],
			"value": Decimal("0.01"),
			"value_currency": "USD"
		},
		{ 
			"names": ["penny","pennies"],
			"value": Decimal("0.01"),
			"value_currency": "GBP"
		},
	],
	"quantity_aliases": {
		"a": Decimal("1"),
		"an": Decimal("1"),
	},
	"prefix_symbols": {
		"$": "USD",
		"€": "EUR",
		"¥": "JPY",
		"£": "GBP",
		"₩": "KRW",
		#"¥": "CNY" # <- damn, same as JPY
	}
}

def amount_config_to_rich_text():
	ac = amount_config
	s = "<h4>Amount Format:</h4>"

	s += "<h3>/u/chaintip &lt;currency_symbol&gt;&lt;decimal&gt;</h3>"
	s += "<h4>with <bg>&lt;currency_symbol&gt;</b> one of...</h4>"
	currency_symbols_str = "\n".join(f"  <li><b>{symbol}</b>: {unit}</li>\n" for symbol, unit in ac["prefix_symbols"].items())
	s += "<ul>\n" + currency_symbols_str + "</ul>\n" 

	s += "<h3>/u/chaintip &lt;quantity&gt; &lt;unit&gt;</h3>"
	s += "<h4>with <bg>&lt;quantity&gt;</b> one of...</h4>"
	quantity_aliases_str = "<li><b>&lt;decimal number&gt;</b></li>\n"
	quantity_aliases_str += "\n".join(f"	<li><b>{alias}</b>: {amount}</li>\n" for alias, amount in ac["quantity_aliases"].items())
	s += "<ul>\n" + quantity_aliases_str + "</ul>\n" 

	s += "<h4>with <bg>&lt;unit&gt;</b> one of...</h4>"
	#units_str = '<tr><td><b>Unit Names</b></td><td align="right"><b>Value</b></td><td><b>Currency</b></td></tr>' 
	units_str = "\n".join(f'	<li><b>{", ".join(unit["names"])}</b>: {unit["value"]} {unit["value_currency"]}</li>' for unit in ac["units"])
	s += "<ul>\n" + units_str + "</ul>\n" 
	return s
