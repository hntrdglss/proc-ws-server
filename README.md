# Proc WebSocket Server

WebSocket server that reads uptime, load, memory, and bandwidth system information from /proc, pushing updates out every 500ms.

I run this on an ASUS RT-N66U router, running Tomato firmware with Optware. On boot, the router executes this script, and a status board connects, displaying the various information.

Code based on https://gist.github.com/3136208 (WebSockets server) and https://gist.github.com/1658752 (ProcNetDev)