on run
	set appPath to POSIX path of (path to me)
	set resPath to appPath & "Contents/Resources/"
	try
		do shell script "lsof -ti:5678 | xargs kill -9 2>/dev/null; true"
	end try
	set launchCmd to "cd " & quoted form of resPath & " && python3 server_analyseur.py"
	tell application "Terminal"
		activate
		do script launchCmd
	end tell
	delay 2
	open location "http://localhost:5678"
end run

