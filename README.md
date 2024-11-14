# lora-aprs-python-client
Lightweight Python application to view iGate logs from https://lora-aprs.live

Note: Some iGates haven't sent logs for a while so pick one you know is currently active.

```
git clone https://github.com/madpsy/lora-aprs-python-client.git
cd lora-aprs-python-client
python3 -m venv venv
source venv/bin/activate
pip3 install -r requirements.txt
python3 lora_aprs_terminal.py
```

Can either select an iGate interactively or specify one as the command line parameter.

![Select iGate](select.png?raw=true "Select iGate")

![Main View](main.png?raw=true "Main View")
