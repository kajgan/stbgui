from Screens.About import CommitInfo
from Screens.ChoiceBox import ChoiceBox
from Screens.MessageBox import MessageBox
from Screens.ParentalControlSetup import ProtectedScreen
from Screens.Screen import Screen
from Screens.Standby import TryQuitMainloop
from Screens.TextBox import TextBox
from Components.config import config
from Components.ActionMap import ActionMap, NumberActionMap
from Components.Ipkg import IpkgComponent
from Components.Sources.StaticText import StaticText
from Components.Slider import Slider
from Tools.BoundFunction import boundFunction
from enigma import eTimer, eDVBDB
from boxbranding import getBoxType, getImageVersion, getMachineBuild
from Tools.Directories import fileExists
from urllib2 import urlopen
import socket
import os
import re

class UpdatePlugin(Screen, ProtectedScreen):
	skin = """
		<screen name="UpdatePlugin" position="center,center" size="550,300">
			<widget name="activityslider" position="0,0" size="550,5"  />
			<widget name="slider" position="0,150" size="550,30"  />
			<widget source="package" render="Label" position="10,30" size="540,20" font="Regular;18" halign="center" valign="center" backgroundColor="#25062748" transparent="1" />
			<widget source="status" render="Label" position="10,180" size="540,100" font="Regular;20" halign="center" valign="center" backgroundColor="#25062748" transparent="1" />
		</screen>"""

	def __init__(self, session, *args):
		Screen.__init__(self, session)
		ProtectedScreen.__init__(self)

		self.sliderPackages = { "dreambox-dvb-modules": 1, "enigma2": 2, "tuxbox-image-info": 3 }

		self.setTitle(_("Software update"))
		self.slider = Slider(0, 4)
		self["slider"] = self.slider
		self.activityslider = Slider(0, 100)
		self["activityslider"] = self.activityslider
		self.status = StaticText(_("Please wait..."))
		self["status"] = self.status
		self.package = StaticText(_("Package list update"))
		self["package"] = self.package
		self.oktext = _("Press OK on your remote control to continue.")

		self.packages = 0
		self.error = 0
		self.processed_packages = []
		self.total_packages = None

		self.channellist_only = 0
		self.channellist_name = ''
		self.updating = False
		self.ipkg = IpkgComponent()
		self.ipkg.addCallback(self.ipkgCallback)
		self.onClose.append(self.__close)

		self["actions"] = ActionMap(["WizardActions"],
		{
			"ok": self.exit,
			"back": self.exit
		}, -1)

		self.activity = 0
		self.activityTimer = eTimer()
		self.activityTimer.callback.append(self.checkTraficLight)
		self.activityTimer.callback.append(self.doActivityTimer)
		self.activityTimer.start(100, True)

	def isProtected(self):
		return config.ParentalControl.setuppinactive.value and\
			(not config.ParentalControl.config_sections.main_menu.value and not config.ParentalControl.config_sections.configuration.value  or hasattr(self.session, 'infobar') and self.session.infobar is None) and\
			config.ParentalControl.config_sections.software_update.value

	def checkTraficLight(self):
		self.activityTimer.callback.remove(self.checkTraficLight)
		self.activityTimer.start(100, False)

		currentTimeoutDefault = socket.getdefaulttimeout()
		socket.setdefaulttimeout(3)
		message = ""
		picon = None
		default = True
		try:
			# TODO: Use Twisted's URL fetcher, urlopen is evil. And it can
			# run in parallel to the package update.
			url = "http://image.openmips.com/status/%s/" % (getImageVersion())
			try:
				status = urlopen(url, timeout=5).read().split('!', 1)
				print status
			except:
				# bypass the certificate check
				from ssl import _create_unverified_context
				status = urlopen(url, timeout=5, context=_create_unverified_context()).read().split('!', 1)
				print status
			# prefer getMachineBuild
			if getMachineBuild() in status[0].split(','):
				message = len(status) > 1 and status[1] or _("The current software might not be stable.\nFor more information see %s.") % ("http://image.openmips.com")
				picon = MessageBox.TYPE_ERROR
				default = False
			# only use getBoxType if no getMachineBuild
			elif getBoxType() in status[0].split(','):
				message = len(status) > 1 and status[1] or _("The current software might not be stable.\nFor more information see %s.") % ("http://image.openmips.com")
				picon = MessageBox.TYPE_ERROR
				default = False
		except:
			message = _("The status of the current software could not be checked because %s can not be reached.") % ("http://image.openmips.com")
			picon = MessageBox.TYPE_ERROR
			default = False
		socket.setdefaulttimeout(currentTimeoutDefault)
		if default:
			self.showDisclaimer()
		else:
			message += "\n" + _("Do you want to update your receiver?")
			self.session.openWithCallback(self.startActualUpdate, MessageBox, message, default = default, picon = picon)

	def showDisclaimer(self, justShow=False):
		if config.usage.show_update_disclaimer.value or justShow:
			message = _("With this disclaimer the openMips team is informing you that we are working with nightly builds and it might be that after the upgrades your set top box \
is not anymore working as expected. Therefore it is recommended to create backups. If something went wrong you can easily and quickly restore. \
When you discover 'bugs' please keep them reported on www.gigablue-support.com.\n\nDo you understand this?")
			list = not justShow and [(_("no"), False), (_("yes"), True), (_("yes") + " " + _("and never show this message again"), "never")] or []
			self.session.openWithCallback(boundFunction(self.disclaimerCallback, justShow), MessageBox, message, list=list)
		else:
			self.startActualUpdate(True)

	def disclaimerCallback(self, justShow, answer):
		if answer == "never":
			config.usage.show_update_disclaimer.value = False
			config.usage.show_update_disclaimer.save()
		if justShow and answer:
			self.ipkgCallback(IpkgComponent.EVENT_DONE, None)
		else:
			self.startActualUpdate(answer)

	def getLatestImageTimestamp(self):
		currentTimeoutDefault = socket.getdefaulttimeout()
		socket.setdefaulttimeout(3)
		try:
			# TODO: Use Twisted's URL fetcher, urlopen is evil. And it can
			# run in parallel to the package update.
			from time import strftime
			from datetime import datetime
			url = "http://image.openmips.com/%s/%s/build-timestamp" % (getImageVersion(), getBoxType())
			try:
				latestImageTimestamp = datetime.fromtimestamp(int(urlopen(url, timeout=5).read())).strftime(_("%Y-%m-%d %H:%M"))
			except:
				# bypass the certificate check
				from ssl import _create_unverified_context
				latestImageTimestamp = datetime.fromtimestamp(int(urlopen(url, timeout=5, context=_create_unverified_context()).read())).strftime(_("%Y-%m-%d %H:%M"))
		except:
			latestImageTimestamp = ""
		print latestImageTimestamp
		print "[SoftwareUpdate] latestImageTimestamp:", latestImageTimestamp
		socket.setdefaulttimeout(currentTimeoutDefault)
		return latestImageTimestamp

	def startActualUpdate(self,answer):
		if answer:
			self.updating = True
			self.ipkg.startCmd(IpkgComponent.CMD_UPDATE)
		else:
			self.close()

	def doActivityTimer(self):
		self.activity += 1
		if self.activity == 100:
			self.activity = 0
		self.activityslider.setValue(self.activity)

	def showUpdateCompletedMessage(self):
		self.setEndMessage(ngettext("Update completed, %d package was installed.", "Update completed, %d packages were installed.", self.packages) % self.packages)

	def ipkgCallback(self, event, param):
		if event == IpkgComponent.EVENT_DOWNLOAD:
			self.status.setText(_("Downloading"))
		elif event == IpkgComponent.EVENT_UPGRADE:
			if self.sliderPackages.has_key(param):
				self.slider.setValue(self.sliderPackages[param])
			self.package.setText(param)
			self.status.setText(_("Upgrading") + ": %s/%s" % (self.packages, self.total_packages))
			if not param in self.processed_packages:
				self.processed_packages.append(param)
				self.packages += 1
		elif event == IpkgComponent.EVENT_INSTALL:
			self.package.setText(param)
			self.status.setText(_("Installing"))
			if not param in self.processed_packages:
				self.processed_packages.append(param)
				self.packages += 1
		elif event == IpkgComponent.EVENT_REMOVE:
			self.package.setText(param)
			self.status.setText(_("Removing"))
			if not param in self.processed_packages:
				self.processed_packages.append(param)
				self.packages += 1
		elif event == IpkgComponent.EVENT_CONFIGURING:
			self.package.setText(param)
			self.status.setText(_("Configuring"))
		elif event == IpkgComponent.EVENT_MODIFIED:
			if config.plugins.softwaremanager.overwriteConfigFiles.value in ("N", "Y"):
				self.ipkg.write(True and config.plugins.softwaremanager.overwriteConfigFiles.value)
			else:
				self.session.openWithCallback(
					self.modificationCallback,
					MessageBox,
					_("A configuration file (%s) has been modified since it was installed.\nDo you want to keep your modifications?") % (param)
				)
		elif event == IpkgComponent.EVENT_ERROR:
			self.error += 1
		elif event == IpkgComponent.EVENT_DONE:
			if self.updating:
				self.updating = False
				self.ipkg.startCmd(IpkgComponent.CMD_UPGRADE_LIST)
			elif self.ipkg.currentCommand == IpkgComponent.CMD_UPGRADE_LIST:
				self.total_packages = len(self.ipkg.getFetchedList())
				if self.total_packages:
					latestImageTimestamp = self.getLatestImageTimestamp()
					if latestImageTimestamp:
						message = _("Latest available openMips %s build is from: %s") % (getImageVersion(), self.getLatestImageTimestamp()) + "\n"
						message += _("Do you want to update your receiver?") + "\n"
					else:
						message = _("Do you want to update your receiver?") + "\n"
					message += "(" + (ngettext("%s updated package available", "%s updated packages available", self.total_packages) % self.total_packages) + ")"
					if self.total_packages > 150:
						message += " " + _("Reflash recommended!")
					choices = [(_("Update and reboot (recommended)"), "cold"),
						(_("Update and ask to reboot"), "hot"),
						#(_("Update channel list only"), "channels"),
						(_("Show packages to be upgraded"), "showlist")]
				else:
					message = _("No updates available")
					choices = []
				if fileExists("/home/root/ipkgupgrade.log"):
					choices.append((_("Show latest upgrade log"), "log"))
				choices.append((_("Show latest commits"), "commits"))
				if not config.usage.show_update_disclaimer.value:
					choices.append((_("Show disclaimer"), "disclaimer"))
				choices.append((_("Cancel"), ""))
				self.session.openWithCallback(self.startActualUpgrade, ChoiceBox, title=message, list=choices)
			elif self.channellist_only > 0:
				if self.channellist_only == 1:
					self.setEndMessage(_("Could not find installed channel list."))
				elif self.channellist_only == 2:
					self.slider.setValue(2)
					self.ipkg.startCmd(IpkgComponent.CMD_REMOVE, {'package': self.channellist_name})
					self.channellist_only += 1
				elif self.channellist_only == 3:
					self.slider.setValue(3)
					self.ipkg.startCmd(IpkgComponent.CMD_INSTALL, {'package': self.channellist_name})
					self.channellist_only += 1
				elif self.channellist_only == 4:
					self.showUpdateCompletedMessage()
					eDVBDB.getInstance().reloadBouquets()
					eDVBDB.getInstance().reloadServicelist()
			elif self.error == 0:
				self.showUpdateCompletedMessage()
			else:
				self.activityTimer.stop()
				self.activityslider.setValue(0)
				error = _("Your receiver might be unusable now. Please consult the manual for further assistance before rebooting your receiver.")
				if self.packages == 0:
					error = _("No updates available. Please try again later.")
				if self.updating:
					error = _("Update failed. Your receiver does not have a working internet connection.")
				self.status.setText(_("Error") +  " - " + error)
		elif event == IpkgComponent.EVENT_LISTITEM:
			if 'enigma2-plugin-settings-' in param[0] and self.channellist_only > 0:
				self.channellist_name = param[0]
				self.channellist_only = 2
		#print event, "-", param
		pass

	def setEndMessage(self, txt):
		self.slider.setValue(4)
		self.activityTimer.stop()
		self.activityslider.setValue(0)
		self.package.setText(txt)
		self.status.setText(self.oktext)

	def startActualUpgrade(self, answer):
		if not answer or not answer[1]:
			self.close()
			return
		if answer[1] == "cold":
			self.session.open(TryQuitMainloop,retvalue=42)
			self.close()
		elif answer[1] == "channels":
			self.channellist_only = 1
			self.slider.setValue(1)
			self.ipkg.startCmd(IpkgComponent.CMD_LIST, args = {'installed_only': True})
		elif answer[1] == "commits":
			self.session.openWithCallback(boundFunction(self.ipkgCallback, IpkgComponent.EVENT_DONE, None), CommitInfo)
		elif answer[1] == "disclaimer":
			self.showDisclaimer(justShow=True)
		elif answer[1] == "showlist":
			text = ""
			for i in [x[0] for x in sorted(self.ipkg.getFetchedList(), key=lambda d: d[0])]:
				text = text and text + "\n" + i or i
			self.session.openWithCallback(boundFunction(self.ipkgCallback, IpkgComponent.EVENT_DONE, None), TextBox, text, _("Packages to update"), True)
		elif answer[1] == "log":
			text = ""
			for i in open("/home/root/ipkgupgrade.log", "r").readlines():
				text += i
			self.session.openWithCallback(boundFunction(self.ipkgCallback, IpkgComponent.EVENT_DONE, None), TextBox, text, _("Packages upgraded"), True)
		else:
			self.ipkg.startCmd(IpkgComponent.CMD_UPGRADE, args = {'test_only': False})

	def modificationCallback(self, res):
		self.ipkg.write(res and "N" or "Y")

	def exit(self):
		if not self.ipkg.isRunning():
			if self.packages != 0 and self.error == 0 and self.channellist_only == 0:
				self.session.openWithCallback(self.exitAnswer, MessageBox, _("Update completed. Do you want to reboot your receiver?"))
			else:
				self.close()
		else:
			if not self.updating:
				self.close()

	def exitAnswer(self, result):
		if result is not None and result:
			self.session.open(TryQuitMainloop,retvalue=2)
		self.close()

	def __close(self):
		self.ipkg.removeCallback(self.ipkgCallback)
