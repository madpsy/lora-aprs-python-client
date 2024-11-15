# lora-aprs-python-client
Lightweight Python application to view iGate logs from https://lora-aprs.live

Check releases on the right for prebuilt binaries.

Logs will appear in real time. As this uses the MQTT endpoint it has no concept of history (except the last iGate log). The up side is it creates no load on the server.

Note: Some iGates haven't sent logs for a while so pick one you know is currently active.

```
git clone https://github.com/madpsy/lora-aprs-python-client.git
cd lora-aprs-python-client
python3 -m venv venv
source venv/bin/activate
pip3 install -r requirements.txt
python3 lora_aprs_terminal.py

or

python3 lora_aprs_terminal.py <iGate callsign>
```

You can build a binary by running this (will output to the `dist` directory):

`pyinstaller --onefile lora_aprs_terminal.py`

Can either select an iGate interactively or specify one as the command line parameter. Use Tab to switch between sections for scrolling and Esc for the iGates menu.

![Main View](main.png?raw=true "Main View")

![Select iGate](select.png?raw=true "Select iGate")

