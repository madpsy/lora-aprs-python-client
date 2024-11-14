import sys  # Import sys to access command-line arguments
import asyncio
import requests
import ssl
import json
from datetime import datetime  # Import datetime module
from aiomqtt import Client
from prompt_toolkit.application import Application
from prompt_toolkit.layout import Layout, HSplit, VSplit
from prompt_toolkit.widgets import TextArea, Label, Frame, VerticalLine
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.styles import Style
from prompt_toolkit.layout.dimension import Dimension  # Import Dimension for dynamic sizing

async def main():
    while True:
        # Check if iGate is passed as a command-line argument
        if len(sys.argv) > 1:
            selected_igate = sys.argv[1].upper()
        else:
            igates = await fetch_igates()
            if not igates:
                print("No iGates found.")
                return

            selected_igate = await select_igate(igates)
            if not selected_igate:
                print("No iGate selected.")
                return

        # Run the main application
        exit_to_select_igate = await run_application(selected_igate)
        if not exit_to_select_igate:
            # User chose to exit the application completely
            break
        # Else, loop back to re-select iGate

async def run_application(selected_igate):
    # Create UI components
    logs_area = TextArea(style="class:logs", scrollbar=True, focusable=True)
    beacons_area = TextArea(style="class:beacons", scrollbar=True, focusable=True)
    decoded_stations_area = TextArea(style="class:decoded", scrollbar=True, focusable=True)
    unique_direct_area = TextArea(style="class:unique_direct", scrollbar=True, focusable=True)
    unique_digipeated_area = TextArea(style="class:unique_digipeated", scrollbar=True, focusable=True)

    # Create frames with dynamic heights
    logs_frame = Frame(body=logs_area, title="Messages", height=Dimension(weight=1))
    beacons_frame = Frame(body=beacons_area, title="Beacons", height=Dimension(weight=1))
    decoded_stations_frame = Frame(body=decoded_stations_area, title="Decoded Locations", height=Dimension(weight=1))
    unique_direct_frame = Frame(body=unique_direct_area, title="Unique Callsigns (Direct)", height=Dimension(weight=1))
    unique_digipeated_frame = Frame(body=unique_digipeated_area, title="Unique Callsigns (Digipeated)", height=Dimension(weight=1))

    # Create layout
    unique_callsigns_frame = VSplit([
        unique_direct_frame,
        VerticalLine(),
        unique_digipeated_frame
    ], height=Dimension(weight=1))

    body = HSplit([
        Label(text=f"Selected iGate: {selected_igate}", style="class:header"),
        Label(text="Use Tab/Shift+Tab to move focus between sections. Use arrow keys to scroll. Esc for iGate menu.", style="class:instructions"),
        logs_frame,
        beacons_frame,
        decoded_stations_frame,
        unique_callsigns_frame,
    ])

    # Define key bindings
    kb = KeyBindings()

    @kb.add('tab')
    def focus_next(event):
        event.app.layout.focus_next()

    @kb.add('s-tab')
    def focus_previous(event):
        event.app.layout.focus_previous()

    @kb.add('c-c')
    @kb.add('q')
    def exit_(event):
        event.app.exit(result=False)  # Return False to signal exit

    @kb.add('escape')
    def exit_to_select(event):
        event.app.exit(result=True)  # Return True to signal exit to select iGate

    style = Style.from_dict({
        'header': 'bold underline',
        'instructions': 'italic',
        'logs': 'bg:#000000 #00ff00',
        'beacons': 'bg:#000000 #00ff00',
        'decoded': 'bg:#000000 #00ff00',
        'unique_direct': 'bg:#000000 #00ff00',
        'unique_digipeated': 'bg:#000000 #00ff00',
    })

    application = Application(
        layout=Layout(body, focused_element=logs_area),  # Set initial focus
        key_bindings=kb,
        full_screen=True,
        style=style,
        mouse_support=True,  # Enable mouse support for clicking to focus
    )

    # Start MQTT client and subscribe to topics
    mqtt_task = asyncio.create_task(mqtt_handler(
        selected_igate,
        logs_area,
        beacons_area,
        decoded_stations_area,
        unique_direct_area,
        unique_digipeated_area,
        application
    ))

    # Run the application and get the exit result
    exit_to_select_igate = await application.run_async()

    # After the application exits, we need to cancel the mqtt_task
    mqtt_task.cancel()
    try:
        await mqtt_task
    except asyncio.CancelledError:
        pass

    return exit_to_select_igate

async def mqtt_handler(
    selected_igate,
    logs_area,
    beacons_area,
    decoded_stations_area,
    unique_direct_area,
    unique_digipeated_area,
    application
):
    topic = f'lora_aprs/{selected_igate}/#'
    unique_direct_set = set()
    unique_digipeated_set = set()

    tls_context = ssl.create_default_context()

    async with Client(
        hostname='hydros.link9.net',
        port=8183,
        transport='websockets',
        tls_context=tls_context,
    ) as client:
        # Subscribe to the topic first
        await client.subscribe(topic)
        # Iterate over the messages
        async for message in client.messages:
            await handle_message(
                str(message.topic),
                message.payload.decode(),
                selected_igate,
                logs_area,
                beacons_area,
                decoded_stations_area,
                unique_direct_area,
                unique_digipeated_area,
                unique_direct_set,
                unique_digipeated_set,
                application
            )

async def handle_message(
    topic,
    message,
    selected_igate,
    logs_area,
    beacons_area,
    decoded_stations_area,
    unique_direct_area,
    unique_digipeated_area,
    unique_direct_set,
    unique_digipeated_set,
    application
):
    # Parse the topic
    parts = topic.split('/')
    if len(parts) == 3:
        # Handle logs messages
        igate = parts[1]
        message_type = parts[2]
        if message_type.lower() == 'logs':
            await append_log_message(message, logs_area, application)
        else:
            # Unknown message type with three parts
            return
    elif len(parts) >= 4:
        igate = parts[1]
        subtopic = parts[2]
        message_type = parts[3]

        if message_type.lower() == 'logs':
            # Handle logs messages (in case they come with four parts)
            await append_log_message(message, logs_area, application)
        elif message_type.lower() == 'json_message':
            if subtopic.upper() == igate.upper():
                # Beacon message
                await append_beacon_message(message, beacons_area, application)
            else:
                # Decoded station message
                await append_decoded_station_message(
                    message,
                    subtopic,
                    decoded_stations_area,
                    unique_direct_area,
                    unique_digipeated_area,
                    unique_direct_set,
                    unique_digipeated_set,
                    application
                )
        else:
            # Unknown message type
            return
    else:
        # Unknown message format
        return

async def append_log_message(message, logs_area, application):
    try:
        log = json.loads(message)
        timestamp = log.get('timestamp', 'Invalid Timestamp')
        try:
            timestamp_dt = datetime.fromisoformat(timestamp)
            local_timestamp = timestamp_dt.astimezone()
            timestamp_str = local_timestamp.strftime('%Y-%m-%d %H:%M:%S %Z')
        except Exception:
            timestamp_str = 'Invalid Timestamp'

        raw_message = log.get('raw_message', 'No Message')
        formatted_message = f"{timestamp_str}: {raw_message}\n"
    except Exception:
        formatted_message = f"Invalid log message: {message}\n"

    logs_area.text = formatted_message + logs_area.text
    # Limit number of lines
    lines = logs_area.text.split('\n')
    if len(lines) > 1000:
        logs_area.text = '\n'.join(lines[:1000])
    application.invalidate()

async def append_beacon_message(message, beacons_area, application):
    try:
        beacon = json.loads(message)
        timestamp = beacon.get('timestamp', 'Invalid Timestamp')
        try:
            timestamp_dt = datetime.fromisoformat(timestamp)
            local_timestamp = timestamp_dt.astimezone()
            timestamp_str = local_timestamp.strftime('%Y-%m-%d %H:%M:%S %Z')
        except Exception:
            timestamp_str = 'Invalid Timestamp'

        destination = beacon.get('destination', 'N/A')
        path = beacon.get('path', 'N/A')
        latitude = beacon.get('latitude', 'N/A')
        longitude = beacon.get('longitude', 'N/A')
        elevation = beacon.get('elevation', 'N/A')
        comment = beacon.get('comment', 'N/A')
        digipeated_via = beacon.get('digipeated_via', 'N/A')
        formatted_message = (
            f"{timestamp_str}: Dest={destination}, Path={path}, "
            f"Coords=({latitude},{longitude}), Elev={elevation}, "
            f"Comment={comment}, Digipeated Via={digipeated_via}\n"
        )
    except Exception:
        formatted_message = f"Invalid beacon message: {message}\n"

    beacons_area.text = formatted_message + beacons_area.text
    lines = beacons_area.text.split('\n')
    if len(lines) > 1000:
        beacons_area.text = '\n'.join(lines[:1000])
    application.invalidate()

async def append_decoded_station_message(
    message,
    callsign,
    decoded_stations_area,
    unique_direct_area,
    unique_digipeated_area,
    unique_direct_set,
    unique_digipeated_set,
    application
):
    try:
        decoded = json.loads(message)
        timestamp = decoded.get('timestamp', 'Invalid Timestamp')
        try:
            timestamp_dt = datetime.fromisoformat(timestamp)
            local_timestamp = timestamp_dt.astimezone()
            timestamp_str = local_timestamp.strftime('%Y-%m-%d %H:%M:%S %Z')
        except Exception:
            timestamp_str = 'Invalid Timestamp'

        destination = decoded.get('destination', 'N/A')
        path = decoded.get('path', 'N/A')
        snr = decoded.get('signal_quality', 'N/A')
        rssi = decoded.get('signal_strength', 'N/A')
        latitude = decoded.get('latitude', 'N/A')
        longitude = decoded.get('longitude', 'N/A')
        elevation = decoded.get('elevation', 'N/A')
        distance = decoded.get('distance', 'N/A')
        battery = decoded.get('battery', 'N/A')
        comment = decoded.get('comment', 'N/A')
        country_code = decoded.get('country_code', 'N/A')
        digipeated_via = decoded.get('digipeated_via', 'N/A')
        formatted_message = (
            f"{timestamp_str}: Callsign={callsign}, Dest={destination}, Path={path}, "
            f"SNR={snr}, RSSI={rssi}, Coords=({latitude},{longitude}), Elev={elevation}, "
            f"Distance={distance}, Battery={battery}, Comment={comment}, "
            f"Country={country_code}, Digipeated Via={digipeated_via}\n"
        )
    except Exception:
        formatted_message = f"Invalid decoded station message: {message}\n"
        digipeated_via = None

    decoded_stations_area.text = formatted_message + decoded_stations_area.text
    lines = decoded_stations_area.text.split('\n')
    if len(lines) > 1000:
        decoded_stations_area.text = '\n'.join(lines[:1000])

    # Process Unique Callsigns
    process_unique_callsigns(
        callsign,
        digipeated_via,
        unique_direct_area,
        unique_digipeated_area,
        unique_direct_set,
        unique_digipeated_set,
        application
    )
    application.invalidate()

def process_unique_callsigns(
    callsign,
    digipeated_via,
    unique_direct_area,
    unique_digipeated_area,
    unique_direct_set,
    unique_digipeated_set,
    application
):
    callsign = callsign.upper()
    if not digipeated_via or digipeated_via.strip() == '' or digipeated_via.upper() == 'N/A':
        if callsign not in unique_direct_set:
            unique_direct_set.add(callsign)
            unique_direct_area.text = callsign + '\n' + unique_direct_area.text
            lines = unique_direct_area.text.split('\n')
            if len(lines) > 1000:
                unique_direct_area.text = '\n'.join(lines[:1000])
    else:
        if callsign not in unique_digipeated_set:
            unique_digipeated_set.add(callsign)
            unique_digipeated_area.text = callsign + '\n' + unique_digipeated_area.text
            lines = unique_digipeated_area.text.split('\n')
            if len(lines) > 1000:
                unique_digipeated_area.text = '\n'.join(lines[:1000])
        digipeated_via = digipeated_via.upper()
        if digipeated_via not in unique_direct_set:
            unique_direct_set.add(digipeated_via)
            unique_direct_area.text = digipeated_via + '\n' + unique_direct_area.text
            lines = unique_direct_area.text.split('\n')
            if len(lines) > 1000:
                unique_direct_area.text = '\n'.join(lines[:1000])
    application.invalidate()

async def fetch_igates():
    try:
        response = requests.get('https://lora-aprs.live/api/callsigns?type=igate')
        if response.status_code == 200:
            data = response.json()
            igates = data.get('igates', [])
            return igates
        else:
            return []
    except Exception as e:
        print(f"Error fetching iGates: {e}")
        return []

async def select_igate(igates):
    igate_tuples = [(igate, igate) for igate in igates]
    from prompt_toolkit.shortcuts import radiolist_dialog
    igate = await radiolist_dialog(
        title="Select iGate",
        text="Please select an iGate:",
        values=igate_tuples,
    ).run_async()
    return igate

if __name__ == '__main__':
    asyncio.run(main())

