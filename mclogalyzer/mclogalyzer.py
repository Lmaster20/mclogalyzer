#!/usr/bin/env python2

#  Copyright 2013 Moritz Hilscher
#
#  This file is part of mclogalyzer.
#
#  mclogalyzer is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  mclogalyzer is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with mclogalyzer.  If not, see <http://www.gnu.org/licenses/>.

import argparse
import datetime
import jinja2
import os
import re
import sys
import time

REGEX_LOGIN_USERNAME = re.compile("\[INFO\] ([^]]+)\[")
REGEX_KICK_USERNAME = re.compile("\[INFO\] CONSOLE: Kicked player ([^ ]*)")

# regular expression to get the username of a chat message
# you need to change this if you have special chat prefixes or stuff like that
# this regex works with chat messages of the format: <prefix username> chat message
REGEX_CHAT_USERNAME = re.compile("\[INFO\] <([^>]*) ([^ ]*)>")

class UserStats:
	def __init__(self, username=""):
		self._username = username
		self._logins = 0

		self._active_days = set()
		self._last_login = None
		self._time = datetime.timedelta()
		self._longest_session = datetime.timedelta()
		
		self._death_count = 0
		self._deaths = {}
		
		self._messages = 0
		
	def handle_logout(self, date):
		if self._last_login is None:
			return
		session = date - self._last_login
		self._time += session
		self._longest_session = max(self._longest_session, session)
		self._last_login = None

	@property
	def username(self):
		return self._username
		
	@property
	def logins(self):
		return self._logins

	@property
	def time(self):
		return format_delta(self._time)

	@property
	def time_per_login(self):
		return format_delta(self._time / self._logins, False)
		
	@property
	def active_days(self):
		return len(self._active_days)

	@property
	def time_per_active_day(self):
		return format_delta(self._time / self.active_days, False)

	@property
	def longest_session(self):
		return format_delta(self._longest_session, False)
		
	@property
	def messages(self):
		return self._messages
		
	@property
	def time_per_message(self):
		if self._messages == 0:
			return "<div class='text-center'>-</div>"
		return format_delta(self._time / self._messages)

class ServerStats:
	def __init__(self):
		self._statistics_since = None
		self._time_played = datetime.timedelta()
		self._max_players = 0
		self._max_players_date = None
		
	@property
	def statistics_since(self):
		return self._statistics_since
		
	@property
	def time_played(self):
		return format_delta(self._time_played, True, True)
	
	@property
	def max_players(self):
		return self._max_players
	
	@property
	def max_players_date(self):
		return self._max_players_date

def grep_date(line):
	try:
		d = time.strptime(" ".join(line.split(" ")[:2]), "%Y-%m-%d %H:%M:%S")
	except ValueError:
		return None
	return datetime.datetime(*(d[0:6]))

def grep_login_username(line):
	search = REGEX_LOGIN_USERNAME.search(line)
	if not search:
		print "### Warning: Unable to find login username:", line
		return ""
	username = search.group(1).lstrip().rstrip()
	return username.decode("ascii", "ignore").encode("ascii", "ignore")

def grep_logout_username(line):
	split = line.split(" ")
	if len(split) < 4:
		print "### Warning: Unable to find username:", line
		return ""
	username = split[3].lstrip().rstrip()
	return username.decode("ascii", "ignore").encode("ascii", "ignore")

def grep_kick_username(line):
	search = REGEX_KICK_USERNAME.search(line)
	if not search:
		print "### Warning: Unable to find kick logout username:", line
		return ""
	return search.group(1)[:-1].decode("ascii", "ignore").encode("ascii", "ignore")

def format_delta(timedelta, days=True, maybe_years=False):
	seconds = timedelta.seconds
	hours = seconds // 3600
	seconds = seconds - (hours * 3600)
	minutes = seconds // 60
	seconds = seconds - (minutes * 60)
	fmt = "%02dh %02dm %02ds" % (hours, minutes, seconds)
	if days:
		if maybe_years:
			days = timedelta.days
			years = days // 365
			days = days - (years * 365)
			if years > 0:
				return ("%d years, %02d days" % (years, days)) + fmt
		return ("%02d days, " % (timedelta.days)) + fmt
	return fmt

def parse_log(logfile, since=None):
	users = {}
	server = ServerStats()
	online_players = set()
	
	date_found = False
	first_date = None
	for line in logfile:
		line = line.rstrip()
		
		if not date_found:
			first_date = grep_date(line)
			if first_date is None:
				continue
			date_found = True
		
		if "logged in with entity id" in line:
			date = grep_date(line)
			if date is None or (since is not None and date < since):
				continue
				
			username = grep_login_username(line)
			if not username:
				continue
			if username not in users:
				users[username] = UserStats(username)
			
			user = users[username]
			user._active_days.add((date.year, date.month, date.day))
			user._logins += 1
			user._last_login = date
			
			online_players.add(username)
			if len(online_players) > server._max_players:
				server._max_players = len(online_players)
				server._max_players_date = date
									
		elif "lost connection" in line or "[INFO] CONSOLE: Kicked player" in line:
			date = grep_date(line)
			if date is None or (since is not None and date < since):
				continue
			
			username = ""
			if "lost connection" in line:
				username = grep_logout_username(line)
			else:
				username = grep_kick_username(line)

			if not username or username.startswith("/"):
				continue
			if username not in users:
				continue
			
			user = users[username]
			user._active_days.add((date.year, date.month, date.day))
			user.handle_logout(date)
			if username in online_players:
				online_players.remove(username)
			
		elif "[INFO] Stopping server" in line:
			date = grep_date(line)
			if date is None or (since is not None and date < since):
				continue
			
			for user in users.values():
				user.handle_logout(date)
			online_players = set()
			
		else:
			search = REGEX_CHAT_USERNAME.search(line)
			if not search:
				continue
			username = search.group(2)
			if username in users:
				users[username]._messages += 1
				
	users = users.values()
	users.sort(key=lambda user: user.time, reverse=True)
	
	server._statistics_since = since if since is not None else first_date
	for user in users:
		server._time_played += user._time
	
	return users, server

def main():
	parser = argparse.ArgumentParser(description="Analyzes the Minecraft Server Log files and generates some statistics.")
	parser.add_argument("-t", "--template", 
					help="the template to generate the output file",
					metavar="template")
	parser.add_argument("--since",
					help="ignores the log before this date, must be in format year-month-day hour:minute:second",
					metavar="<datetime>")
	parser.add_argument("log",
					help="the server log file",
					metavar="<logfile>")
	parser.add_argument("output",
					help="the output html file",
					metavar="<outputfile>")
	args = vars(parser.parse_args())
	
	since = None
	if args["since"] is not None:
		try:
			d = time.strptime(args["since"], "%Y-%m-%d %H:%M:%S")
		except ValueError:
			print "Invalid datetime format! The format must be year-month-day hour:minute:second ."
			sys.exit(1)
		since = datetime.datetime(*(d[0:6]))
	
	f = open(args["log"])
	users, server = parse_log(f, since)
	f.close()

	template_path = os.path.join(os.path.dirname(__file__), "template.html")
	if args["template"] is not None:
		template_path = args["template"]
	template_dir = os.path.dirname(template_path)
	template_name = os.path.basename(template_path)
	#print template_path
	#print template_dir, template_name
	if not os.path.exists(template_path):
		print "Unable to find template file %s!" % template_path
		sys.exit(1) 
	
	env = jinja2.Environment(loader=jinja2.FileSystemLoader(template_dir))
	template = env.get_template(template_name)
	
	f = open(args["output"], "w")
	f.write(template.render(users=users, 
							server=server,
							last_update=time.strftime("%Y-%m-%d %H:%M:%S")))
	f.close()
	
if __name__ == "__main__":
	main()
