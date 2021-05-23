from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtWidgets import *

from electroncash.util import PrintError, print_error
from electroncash.i18n import _
from electroncash import version, bitcoin, address
from electroncash.networks import MainNet
from electroncash_gui.qt import *
from electroncash_gui.qt.util import *
import base64, sys, requests, threading, time

class UpdateChecker(QWidget, PrintError):
	''' A window that checks for updates.

	This class was copied and adapted from electroncash_gui/qt/UpdateChecker

	Main difference is that it doesn't handle variants: there's simply a single
	latest version reflected in latest_version.json

	'''
	# Note: it's guaranteed that every call to do_check() will either result
	# in a 'checked' signal or a 'failed' signal to be emitted.
	# got_new_version is only emitted if the new version is actually newer than
	# our version.
	checked = pyqtSignal(object) # emitted whenever the server gave us a (properly signed) version string. may or may not mean it's a new version.
	got_new_version = pyqtSignal(object) # emitted in tandem with 'checked' above ONLY if the server gave us a (properly signed) version string we recognize as *newer*
	failed = pyqtSignal(str) # emitted when there is an exception, network error, or verify error on version check.

	_req_finished = pyqtSignal(object) # internal use by _Req thread
	_dl_prog = pyqtSignal(object, int) # [0 -> 100] range

	url = "https://raw.githubusercontent.com/molecular/chaintipper/release/update_checker/latest_version.json"

	VERSION_ANNOUNCEMENT_SIGNING_ADDRESSES = (
		address.Address.from_string("bitcoincash:qzz3zl6sl7zahh00dnzw0vrs0f3rxral9uedywqlfw", net=MainNet), # molecular#123
	)

	def __init__(self, parent, local_version):
		super().__init__(parent)

		self.local_version = local_version

		self._req_finished.connect(self._on_req_finished)

		self.active_req = None
		self.last_checked_ts = 0.0

	def _process_server_reply(self, metainfo):

		# example lastest_version.json
		# {
		# 	"version": "1.0-beta6",
		# 	"uri": "http://criptolayer.net:/var/www/criptolayer.net/Pk4p2VyxVtOAkWzq/ChainTipper-1.0-beta6.zip",
		# 	"sha256": "6336f94972585435c07d6c79105622320370783b719d57863d45b1638a909d37",
		# 	"sig_ca": "molecular#123",
		# 	"sig_addr": "bitcoincash:qzz3zl6sl7zahh00dnzw0vrs0f3rxral9uedywqlfw",
		# 	// message to sign: "<sha256>"
		# 	"sig_of_sha256": "ICU5+tNqcqvJ3gsIZdchfWoIadrri/edcYU1o9UUBuPGbueD+OS9bE0yhH7C6cjmfV3oJHTz8t6s4bgzTjZbEiI="
		# }

		# for k, v in metainfo.items():
		# 	self.print_error("   ", k, " = ", v)

		# check if installed version is latest
		if metainfo["version"] == self.local_version:
			self.print_error(f"most recent version {metainfo['version']} already installed.")
			self.checked.emit(metainfo)
			return 

		# get stuff from metainfo
		adr = address.Address.from_string(metainfo["sig_addr"], net=MainNet) # may raise
		sig_of_sha256 = metainfo["sig_of_sha256"]

		# check adr is in list of announcement signers
		if adr not in self.VERSION_ANNOUNCEMENT_SIGNING_ADDRESSES:
			raise Exception(f"signig address {adr} not in list of signing addresses")

		# check signature <sha256>
		msg = metainfo["sha256"]
		metainfo["sig_msg"] = msg # for display to user
		is_verified = bitcoin.verify_message(adr, base64.b64decode(sig), msg.encode('utf-8'), net=MainNet)
		self.print_error("signature verified: ", is_verified)

		if is_verified:
			self.got_new_version.emit(metainfo)
		else:
			self.failed.emit("invalid signature, please contact developer")

	def cancel_active(self):
		if self.active_req:
			self.active_req.abort()
			self.active_req = None
			self._err_fail()

	def cancel_or_check(self):
		if self.active_req:
			self.cancel_active()
		else:
			self.do_check(force=True)

	# Note: calls to do_check() will either result in a 'checked' signal or
	# a 'failed' signal to be emitted (and possibly also 'got_new_version')
	def do_check(self, force=False):
		if force:
			self.cancel_active() # no-op if none active
		if not self.active_req:
			self.last_checked_ts = time.time()
			self.active_req = _Req(self)

	def did_check_recently(self, secs=10.0):
		return time.time() - self.last_checked_ts < secs

	_error_val = 0xdeadb33f

	def _got_reply(self, req):
		if not req.aborted and req.json:
			try:
				self._process_server_reply(req.json)
			except:
				import traceback
				self.print_error(traceback.format_exc())

	def _on_req_finished(self, req):
		adjective = ''
		if req is self.active_req:
			self._got_reply(req)
			self.active_req = None
			adjective = "Active"
		if req.aborted:
			adjective = "Aborted"
		self.print_error("{}".format(adjective),req.diagnostic_name(),"finished")


class _Req(threading.Thread, PrintError):
	def __init__(self, checker):
		super().__init__(daemon=True)
		self.checker = checker
		self.url = self.checker.url
		self.aborted = False
		self.json = None
		self.start()

	def abort(self):
		self.aborted = True

	def diagnostic_name(self):
		return "{}@{}".format(__class__.__name__, id(self)&0xffff)

	def run(self):
		self.checker._dl_prog.emit(self, 10)
		try:
			self.print_error("Requesting from",self.url,"...")
			self.json, self.url = self._do_request(self.url)
			self.checker._dl_prog.emit(self, 100)
		except:
			self.checker._dl_prog.emit(self, 25)
			import traceback
			self.print_error(traceback.format_exc())
		finally:
			self.checker._req_finished.emit(self)

	def _do_request(self, url):
		response = requests.get(url, allow_redirects=True, timeout=30.0) # will raise requests.exceptions.Timeout on timeout

		if response.status_code != 200:
			raise RuntimeError(response.status_code, response.text)
		self.print_error("got response {} bytes".format(len(response.text)))
		self.print_error(response.text)
		return response.json(), response.url
