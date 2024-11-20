import sys  # Import sys to access command-line arguments
import asyncio
import ssl
import json
import aiohttp  # Import aiohttp for asynchronous HTTP requests
from datetime import datetime, timedelta  # Import datetime and timedelta
from collections import OrderedDict  # For maintaining order of callsigns
from aiomqtt import Client
from prompt_toolkit.application import Application
from prompt_toolkit.layout import Layout, HSplit, VSplit, Window
from prompt_toolkit.widgets import TextArea, Label, Frame, VerticalLine
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.styles import Style
from prompt_toolkit.layout.dimension import Dimension  # For dynamic sizing
from prompt_toolkit.formatted_text import HTML  # For colored status indicators
from prompt_toolkit.shortcuts import radiolist_dialog, input_dialog  # Import for dialogs

import re  # For callsign validation

# Version of the application
version = '1.5'

if sys.platform.startswith('win'):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


async def main():
    current_igate = None  # Initialize current iGate as None
    first_run = True       # Flag to indicate the first iteration

    while True:
        if first_run and len(sys.argv) > 1:
            selected_igate = sys.argv[1].upper()
            if validate_callsign(selected_igate):
                current_igate = selected_igate  # Set current iGate
                first_run = False
                print(f"Using iGate from command-line argument: {selected_igate}")  # Logging
            else:
                print(f"Invalid iGate callsign provided via command-line: {selected_igate}")
                return
        else:
            igates = await fetch_igates()
            if not igates:
                print("No iGates found.")
                return

            # Pass current_igate as default for pre-selection
            selected_igate = await select_igate(igates, default=current_igate)
            if not selected_igate:
                print("No iGate selected.")
                return
            current_igate = selected_igate  # Update current iGate
            print(f"Selected iGate: {selected_igate}")  # Logging

        # Run the main application
        exit_to_select_igate = await run_application(selected_igate, current_igate)
        if not exit_to_select_igate:
            # User chose to exit the application completely
            break
        # Else, loop back to re-select iGate


async def run_application(selected_igate, current_igate):
    # Initialize connection status
    connection_status = {'status': False}

    # Initialize reset_in_progress flag
    reset_in_progress = {'value': False}

    # Check for updates
    new_version_available = await check_for_updates(version)

    # Create the 'new_version_label' based on 'new_version_available'
    if new_version_available:
        new_version_label = Label(text='New Version Available: https://github.com/madpsy/lora-aprs-python-client', style='class:new_version')
    else:
        new_version_label = Label(text='')

    # Create UI components
    logs_area = TextArea(style="class:logs", scrollbar=True, focusable=True, read_only=True)
    beacons_area = TextArea(style="class:beacons", scrollbar=True, focusable=True, read_only=True)
    decoded_stations_area = TextArea(style="class:decoded", scrollbar=True, focusable=True, read_only=True)
    unique_direct_area = TextArea(style="class:unique_direct", scrollbar=True, focusable=True, read_only=True)
    unique_digipeated_area = TextArea(style="class:unique_digipeated", scrollbar=True, focusable=True, read_only=True)

    # Initialize data structures
    unique_direct_dict = OrderedDict()
    unique_digipeated_dict = OrderedDict()
    beacons_dict = OrderedDict()            # New dictionary for beacons
    decoded_stations_dict = OrderedDict()   # New dictionary for decoded stations

    # Create MQTT Status Indicator with formatted text
    mqtt_status_indicator = Label(text=generate_status_text(connection_status['status']),
                                  style="")  # Style is handled within the text

    # Create frames with dynamic heights
    logs_frame = Frame(body=logs_area, title="Messages", height=Dimension(weight=1))
    beacons_frame = Frame(body=beacons_area, title="Beacons", height=Dimension(weight=1))
    decoded_stations_frame = Frame(body=decoded_stations_area, title="Decoded Messages", height=Dimension(weight=1))
    unique_direct_frame = Frame(body=unique_direct_area, title="Unique Callsigns (Direct)", height=Dimension(weight=1))
    unique_digipeated_frame = Frame(body=unique_digipeated_area, title="Unique Callsigns (Digipeated)", height=Dimension(weight=1))

    # Modify Usage Info Line to Include MQTT Status Indicator
    usage_info = VSplit([
        Label(text="Use Tab/Shift+Tab to move focus between sections. Use arrow keys to scroll. 'r' to reset tables and reconnect. Esc to open iGate menu. Text size: Ctrl +/-",
              style="class:instructions"),
        mqtt_status_indicator
    ], padding=1)

    # Create header with Selected iGate and New Version Available message
    header = VSplit([
        Label(text=f"Selected iGate: {selected_igate}", style="class:header"),
        Window(width=1, char=' '),  # Spacer
        new_version_label,
        ], padding=1)

    # Create layout
    unique_callsigns_frame = VSplit([
        unique_direct_frame,
        VerticalLine(),
        unique_digipeated_frame
    ], height=Dimension(weight=1))

    body = HSplit([
        header,
        usage_info,  # Replace previous instructions Label with the new usage_info containing status
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
        print("Exit key pressed. Exiting application.")  # Logging
        event.app.exit(result=False)  # Return False to signal exit

    @kb.add('escape')
    def exit_to_select(event):
        print("Escape key pressed. Exiting to select iGate.")  # Logging
        event.app.exit(result=True)  # Return True to signal exit to select iGate

    @kb.add('r')
    def reset_and_reconnect(event):
        if not reset_in_progress['value']:
            reset_in_progress['value'] = True
            asyncio.create_task(handle_reset_and_reconnect(
                selected_igate,       # Pass the current iGate
                unique_direct_dict,
                unique_digipeated_dict,
                unique_direct_area,
                unique_digipeated_area,
                beacons_dict,               # Pass beacons_dict
                decoded_stations_dict,      # Pass decoded_stations_dict
                mqtt_task_container,
                connection_status,
                mqtt_status_indicator,
                application,
                logs_area,            # Pass logs_area
                beacons_area,         # Pass beacons_area
                decoded_stations_area, # Pass decoded_stations_area
                reset_in_progress,      # Pass the reset flag
                update_seen_task_container  # Pass the task container
            ))
        else:
            pass  # Do nothing if reset is already in progress

    style = get_style()

    application = Application(
        layout=Layout(body, focused_element=logs_area),  # Set initial focus
        key_bindings=kb,
        full_screen=True,
        style=style,
        mouse_support=True,  # Enable mouse support for clicking to focus
    )

    # Container to hold MQTT task for easy cancellation and reconnection
    mqtt_task_container = {'task': None}

    # Container to hold the update_seen_task for easy cancellation and reconnection
    update_seen_task_container = {'task': None}

    # Start MQTT Handler Task and Store in Container
    mqtt_task_container['task'] = asyncio.create_task(mqtt_handler(
        selected_igate,
        logs_area,
        beacons_area,
        decoded_stations_area,
        unique_direct_area,
        unique_digipeated_area,
        unique_direct_dict,
        unique_digipeated_dict,
        beacons_dict,               # Pass beacons_dict
        decoded_stations_dict,      # Pass decoded_stations_dict
        application,
        connection_status,
        mqtt_status_indicator
    ))

    # Start the background task for updating "Seen" times
    update_seen_task_container['task'] = asyncio.create_task(update_seen_times(
        unique_direct_dict,
        unique_digipeated_dict,
        beacons_dict,
        decoded_stations_dict,
        unique_direct_area,
        unique_digipeated_area,
        beacons_area,
        decoded_stations_area,
        application
    ))

    # Run the application and get the exit result
    exit_to_select_igate = await application.run_async()

    # After the application exits, we need to cancel the mqtt_task and update_seen_task
    if update_seen_task_container['task'] is not None:
        update_seen_task_container['task'].cancel()
        try:
            await update_seen_task_container['task']
        except asyncio.CancelledError:
            pass

    if mqtt_task_container['task'] is not None:
        mqtt_task_container['task'].cancel()
        try:
            await mqtt_task_container['task']
        except asyncio.CancelledError:
            pass

    return exit_to_select_igate


async def handle_reset_and_reconnect(
    selected_igate,       # Current iGate
    unique_direct_dict,
    unique_digipeated_dict,
    unique_direct_area,
    unique_digipeated_area,
    beacons_dict,
    decoded_stations_dict,
    mqtt_task_container,
    connection_status,
    mqtt_status_indicator,
    application,
    logs_area,
    beacons_area,
    decoded_stations_area,
    reset_in_progress,
    update_seen_task_container  # Pass the update_seen_task container
):
    try:
        # Cancel the update_seen_task before clearing dictionaries
        if update_seen_task_container['task'] is not None:
            update_seen_task_container['task'].cancel()
            try:
                await update_seen_task_container['task']
            except asyncio.CancelledError:
                pass

        # Clear data structures
        unique_direct_dict.clear()
        unique_digipeated_dict.clear()
        beacons_dict.clear()
        decoded_stations_dict.clear()

        # Clear UI tables
        unique_direct_area.text = ""
        unique_digipeated_area.text = ""
        beacons_area.text = ""
        decoded_stations_area.text = ""
        logs_area.text = ""

        # Update status to Disconnected
        connection_status['status'] = False
        mqtt_status_indicator.text = generate_status_text(connection_status['status'])
        application.invalidate()

        # Cancel existing MQTT task
        if mqtt_task_container['task'] is not None:
            mqtt_task_container['task'].cancel()
            try:
                await mqtt_task_container['task']
            except asyncio.CancelledError:
                pass

        # Start a new MQTT handler
        mqtt_task_container['task'] = asyncio.create_task(mqtt_handler(
            selected_igate,
            logs_area,
            beacons_area,
            decoded_stations_area,
            unique_direct_area,
            unique_digipeated_area,
            unique_direct_dict,
            unique_digipeated_dict,
            beacons_dict,
            decoded_stations_dict,
            application,
            connection_status,
            mqtt_status_indicator
        ))

        # Restart the update_seen_task
        update_seen_task_container['task'] = asyncio.create_task(update_seen_times(
            unique_direct_dict,
            unique_digipeated_dict,
            beacons_dict,
            decoded_stations_dict,
            unique_direct_area,
            unique_digipeated_area,
            beacons_area,
            decoded_stations_area,
            application
        ))
    finally:
        # Reset the reset_in_progress flag
        reset_in_progress['value'] = False


def generate_status_text(is_connected):
    if is_connected:
        return [
            ('class:status_connected_dot', '● '),
            ('class:status_connected_text', 'Connected')
        ]
    else:
        return [
            ('class:status_disconnected_dot', '● '),
            ('class:status_disconnected_text', 'Disconnected')
        ]


async def mqtt_handler(
    selected_igate,
    logs_area,
    beacons_area,
    decoded_stations_area,
    unique_direct_area,
    unique_digipeated_area,
    unique_direct_dict,
    unique_digipeated_dict,
    beacons_dict,
    decoded_stations_dict,
    application,
    connection_status,
    mqtt_status_indicator
):
    topic = f'lora_aprs/{selected_igate}/#'

    tls_context = ssl.create_default_context()

    try:
        async with Client(
            hostname='hydros.link9.net',
            port=8183,
            transport='websockets',
            tls_context=tls_context,
        ) as client:
            # Update connection status to Connected
            connection_status['status'] = True
            mqtt_status_indicator.text = generate_status_text(connection_status['status'])
            application.invalidate()

            # Subscribe to the topic
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
                    unique_direct_dict,
                    unique_digipeated_dict,
                    beacons_dict,
                    decoded_stations_dict,
                    application
                )
    except Exception as e:
        # Update connection status to Disconnected on error
        connection_status['status'] = False
        mqtt_status_indicator.text = generate_status_text(connection_status['status'])
        application.invalidate()
        print(f"Error in MQTT handler: {e}")  # Retain this for error debugging


async def handle_message(
    topic,
    message,
    selected_igate,
    logs_area,
    beacons_area,
    decoded_stations_area,
    unique_direct_area,
    unique_digipeated_area,
    unique_direct_dict,
    unique_digipeated_dict,
    beacons_dict,
    decoded_stations_dict,
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
                await append_beacon_message(message, beacons_area, application, beacons_dict)
            else:
                # Decoded station message
                callsign = subtopic  # Assuming the callsign is the subtopic
                await append_decoded_station_message(
                    message,
                    callsign,
                    decoded_stations_area,
                    unique_direct_area,
                    unique_digipeated_area,
                    unique_direct_dict,
                    unique_digipeated_dict,
                    decoded_stations_dict,    # Pass decoded_stations_dict
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
            # Remove timezone from timestamp
            timestamp_str = local_timestamp.strftime('%Y-%m-%d %H:%M:%S')
        except Exception:
            timestamp_str = 'Invalid Timestamp'

        raw_message = log.get('raw_message', 'No Message') or 'No Message'
        formatted_message = f"{timestamp_str} {raw_message}\n"
    except Exception:
        formatted_message = f"Invalid log message: {message}\n"

    logs_area.text = formatted_message + logs_area.text
    # Limit number of lines
    lines = logs_area.text.split('\n')
    if len(lines) > 1000:
        logs_area.text = '\n'.join(lines[:1000])
    application.invalidate()


def truncate_text(text, max_length=20):
    if len(text) > max_length:
        return text[:max_length-3] + '...'
    return text


async def append_beacon_message(message, beacons_area, application, beacons_dict):
    try:
        beacon = json.loads(message)
        timestamp = beacon.get('timestamp', 'Invalid Timestamp')
        try:
            timestamp_dt = datetime.fromisoformat(timestamp)
            local_timestamp = timestamp_dt.astimezone()
            # Remove timezone from timestamp
            timestamp_str = local_timestamp.strftime('%Y-%m-%d %H:%M:%S')
        except Exception:
            timestamp_str = 'Invalid Timestamp'

        destination = beacon.get('destination', 'N/A') or 'N/A'
        path = beacon.get('path', 'N/A') or 'N/A'
        path = str(path)  # Ensure path is a string

        latitude = beacon.get('latitude', 'N/A') or 'N/A'
        longitude = beacon.get('longitude', 'N/A') or 'N/A'
        elevation = beacon.get('elevation', 'N/A') or 'N/A'
        battery = beacon.get('battery', 'N/A') or 'N/A'
        # Increase max_length to 40 for Beacons section
        comment = truncate_text(beacon.get('comment', 'N/A') or 'N/A', max_length=40)
        digipeated_via = beacon.get('digipeated_via', 'N/A') or 'N/A'
        digipeated_via = str(digipeated_via)  # Ensure digipeated_via is a string
        country_code = beacon.get('country_code', 'N/A') or 'N/A'  # Assuming country_code is part of beacon

        # Create a unique identifier for the beacon, e.g., timestamp + destination
        beacon_id = f"{timestamp_str}_{destination}"

        # Update the beacons_dict
        beacons_dict[beacon_id] = {
            'Time': timestamp_str,
            'Destination': destination,
            'Path': path,
            'Latitude': latitude,
            'Longitude': longitude,
            'Elevation': elevation,
            'Battery': battery,
            'Comment': comment,
            'Digipeated_Via': digipeated_via,
            'Country': country_code,
            'last_seen': datetime.now()
        }

        # Refresh the beacons area
        refresh_beacons_area(beacons_dict, beacons_area)

    except Exception as e:
        error_message = f"Invalid beacon message: {message}\nError: {e}\n"
        beacons_area.text = error_message + beacons_area.text
        # Optionally limit the number of displayed beacons
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
    unique_direct_dict,
    unique_digipeated_dict,
    decoded_stations_dict,
    application
):
    try:
        decoded = json.loads(message)
        timestamp = decoded.get('timestamp', 'Invalid Timestamp')
        try:
            timestamp_dt = datetime.fromisoformat(timestamp)
            local_timestamp = timestamp_dt.astimezone()
            # Remove timezone from timestamp
            timestamp_str = local_timestamp.strftime('%Y-%m-%d %H:%M:%S')
        except Exception:
            timestamp_str = 'Invalid Timestamp'

        destination = decoded.get('destination', 'N/A') or 'N/A'
        path = decoded.get('path', 'N/A') or 'N/A'
        path = str(path)  # Ensure path is a string

        snr = decoded.get('signal_quality', 'N/A') or 'N/A'
        rssi = decoded.get('signal_strength', 'N/A') or 'N/A'
        latitude = decoded.get('latitude', 'N/A') or 'N/A'
        longitude = decoded.get('longitude', 'N/A') or 'N/A'
        elevation = decoded.get('elevation', 'N/A') or 'N/A'
        distance = decoded.get('distance', 'N/A') or 'N/A'        # New
        battery = decoded.get('battery', 'N/A') or 'N/A'          # New
        comment = truncate_text(decoded.get('comment', 'N/A') or 'N/A')  # Truncate comment to default length
        country_code = decoded.get('country_code', 'N/A') or 'N/A'
        digipeated_via = decoded.get('digipeated_via', 'N/A') or 'N/A'
        digipeated_via = str(digipeated_via)  # Ensure digipeated_via is a string

        # Create a unique identifier for the decoded station, e.g., timestamp + callsign
        station_id = f"{timestamp_str}_{callsign}"

        # Update the decoded_stations_dict
        decoded_stations_dict[station_id] = {
            'Time': timestamp_str,
            'Callsign': callsign,
            'Destination': destination,
            'Path': path,
            'SNR': snr,
            'RSSI': rssi,
            'Latitude': latitude,
            'Longitude': longitude,
            'Elevation': elevation,
            'Distance': distance,
            'Battery': battery,
            'Comment': comment,
            'Country': country_code,
            'Digipeated_Via': digipeated_via,
            'last_seen': datetime.now(),
            'Count': 1                    # Initialize count
        }

        # Process Unique Callsigns
        process_unique_callsigns(
            callsign,
            digipeated_via,
            snr,
            rssi,
            country_code,
            distance,
            elevation,
            battery,
            decoded_stations_dict,
            unique_direct_dict,
            unique_digipeated_dict,
            unique_direct_area,
            unique_digipeated_area,
            application
        )

        # Refresh the decoded stations area
        refresh_decoded_stations_area(decoded_stations_dict, decoded_stations_area)

    except Exception as e:
        error_message = f"Invalid decoded station message: {message}\nError: {e}\n"
        decoded_stations_area.text = error_message + decoded_stations_area.text
        # Optionally limit the number of displayed stations
        lines = decoded_stations_area.text.split('\n')
        if len(lines) > 1000:
            decoded_stations_area.text = '\n'.join(lines[:1000])

    application.invalidate()


def process_unique_callsigns(
    callsign,
    digipeated_via,
    snr,
    rssi,
    country_code,
    distance,
    elevation,
    battery,
    decoded_stations_dict,
    unique_direct_dict,
    unique_digipeated_dict,
    unique_direct_area,
    unique_digipeated_area,
    application
):
    callsign = callsign.upper()
    current_time = datetime.now()

    if not digipeated_via or digipeated_via.strip() == '' or digipeated_via.upper() == 'N/A':
        # Direct call
        if callsign in unique_direct_dict:
            # Increment the count
            unique_direct_dict[callsign]['Count'] += 1
            # Update other fields
            unique_direct_dict[callsign]['SNR'] = snr
            unique_direct_dict[callsign]['RSSI'] = rssi
            unique_direct_dict[callsign]['Country'] = country_code
            unique_direct_dict[callsign]['Distance'] = distance if distance != 'N/A' else 'N/A'
            unique_direct_dict[callsign]['Elevation'] = elevation if elevation != 'N/A' else 'N/A'

            # Set 'Battery' only if not set by digipeated section
            if not (callsign in unique_digipeated_dict and
                    unique_digipeated_dict[callsign].get('Battery') and
                    unique_digipeated_dict[callsign]['Battery'] != 'N/A'):
                unique_direct_dict[callsign]['Battery'] = battery if battery != 'N/A' else unique_direct_dict[callsign].get('Battery', 'N/A')

            unique_direct_dict[callsign]['last_seen'] = current_time
        else:
            # Initialize 'Battery' only if not set by digipeated section
            if callsign in unique_digipeated_dict and \
               unique_digipeated_dict[callsign].get('Battery') and \
               unique_digipeated_dict[callsign]['Battery'] != 'N/A':
                battery_value = 'N/A'  # Do not set battery from direct message
            else:
                battery_value = battery if battery != 'N/A' else 'N/A'

            unique_direct_dict[callsign] = {
                'SNR': snr,
                'RSSI': rssi,
                'Country': country_code,
                'Distance': distance if distance != 'N/A' else 'N/A',
                'Elevation': elevation if elevation != 'N/A' else 'N/A',
                'Battery': battery_value,
                'last_seen': current_time,
                'Count': 1
            }
    else:
        # Digipeated call
        if callsign in unique_digipeated_dict:
            # Increment the count
            unique_digipeated_dict[callsign]['Count'] += 1
            # Update other fields
            unique_digipeated_dict[callsign]['Digipeated_Via'] = digipeated_via
            unique_digipeated_dict[callsign]['Country'] = country_code
            unique_digipeated_dict[callsign]['Distance'] = distance if distance != 'N/A' else 'N/A'
            unique_digipeated_dict[callsign]['Elevation'] = elevation if elevation != 'N/A' else 'N/A'
            unique_digipeated_dict[callsign]['Battery'] = battery if battery != 'N/A' else unique_digipeated_dict[callsign].get('Battery', 'N/A')
            unique_digipeated_dict[callsign]['last_seen'] = current_time
        else:
            unique_digipeated_dict[callsign] = {
                'Digipeated_Via': digipeated_via,
                'Country': country_code,
                'Distance': distance if distance != 'N/A' else 'N/A',
                'Elevation': elevation if elevation != 'N/A' else 'N/A',
                'Battery': battery if battery != 'N/A' else 'N/A',
                'last_seen': current_time,
                'Count': 1
            }

        # Add 'digipeated_via' to direct callsigns without setting 'Battery'
        digipeated_via_callsign = digipeated_via.upper()
        if digipeated_via_callsign != 'N/A' and digipeated_via_callsign.strip() != '':
            if digipeated_via_callsign in unique_direct_dict:
                unique_direct_dict[digipeated_via_callsign]['Count'] += 1
                unique_direct_dict[digipeated_via_callsign]['SNR'] = snr
                unique_direct_dict[digipeated_via_callsign]['RSSI'] = rssi
                # Do NOT set 'Battery' for digipeated_via_callsign
                unique_direct_dict[digipeated_via_callsign]['Battery'] = unique_direct_dict[digipeated_via_callsign].get('Battery', 'N/A')
                unique_direct_dict[digipeated_via_callsign]['last_seen'] = current_time
            else:
                unique_direct_dict[digipeated_via_callsign] = {
                    'SNR': snr,
                    'RSSI': rssi,
                    'Country': 'N/A',
                    'Distance': 'N/A',
                    'Elevation': 'N/A',
                    'Battery': 'N/A',  # Set 'Battery' to 'N/A'
                    'last_seen': current_time,
                    'Count': 1
                }

    # Refresh the displays
    refresh_unique_direct_area(unique_direct_dict, unique_direct_area)
    refresh_unique_digipeated_area(unique_digipeated_dict, unique_digipeated_area, unique_direct_dict)
    application.invalidate()


def refresh_unique_direct_area(unique_direct_dict, unique_direct_area):
    # Define column headers with specified widths, including 'Battery' before 'Count' and 'Count' before 'Seen'
    headers = f"{'Callsign':<10} {'SNR':<6} {'RSSI':<6} {'Country':<7} {'Distance':<8} {'Elevation':<9} {'Battery':<7} {'Count':<5} {'Seen':<12}\n"
    separator = f"{'-'*10} {'-'*6} {'-'*6} {'-'*7} {'-'*8} {'-'*9} {'-'*7} {'-'*5} {'-'*12}\n"
    content = headers + separator
    current_time = datetime.now()

    # Sort the unique_direct_dict based on 'last_seen' in descending order
    sorted_direct = sorted(unique_direct_dict.items(), key=lambda item: item[1]['last_seen'], reverse=True)

    for callsign, data in sorted_direct:
        # Calculate the time difference
        time_diff = current_time - data['last_seen']
        seen_str = format_timedelta(time_diff)
        # Safely get each field with defaults
        snr = data.get('SNR') or 'N/A'
        rssi = data.get('RSSI') or 'N/A'
        country = data.get('Country') or 'N/A'
        distance = data.get('Distance') or 'N/A'
        elevation = data.get('Elevation') or 'N/A'
        battery = data.get('Battery') or 'N/A'  # New field
        count = data.get('Count') or 0
        content += f"{callsign:<10} {snr:<6} {rssi:<6} {country:<7} {distance:<8} {elevation:<9} {battery:<7} {count:<5} {seen_str:<12}\n"

    unique_direct_area.text = content
    # Optionally limit the number of displayed callsigns
    lines = unique_direct_area.text.split('\n')
    if len(lines) > 1001:  # 1000 data lines + headers
        unique_direct_area.text = '\n'.join(lines[:1001])


def refresh_unique_digipeated_area(unique_digipeated_dict, unique_digipeated_area, unique_direct_dict):
    # Define column headers with specified widths, including 'Battery' before 'Count' and 'Count' before 'Seen'
    headers = f"{'Callsign':<10} {'Digipeated Via':<14} {'Country':<7} {'Distance':<8} {'Elevation':<9} {'Battery':<7} {'Count':<5} {'Seen':<12}\n"
    separator = f"{'-'*10} {'-'*14} {'-'*7} {'-'*8} {'-'*9} {'-'*7} {'-'*5} {'-'*12}\n"
    content = headers + separator
    current_time = datetime.now()

    # Sort the unique_digipeated_dict based on 'last_seen' in descending order
    sorted_digipeated = sorted(unique_digipeated_dict.items(), key=lambda item: item[1]['last_seen'], reverse=True)

    for callsign, data in sorted_digipeated:
        # Calculate the time difference
        time_diff = current_time - data['last_seen']
        seen_str = format_timedelta(time_diff)
        digipeated_via = data.get('Digipeated_Via') or 'N/A'
        country = data.get('Country') or 'N/A'
        distance = data.get('Distance') or 'N/A'
        elevation = data.get('Elevation') or 'N/A'
        battery = data.get('Battery') or 'N/A'  # New field
        count = data.get('Count') or 0

        content += f"{callsign:<10} {digipeated_via:<14} {country:<7} {distance:<8} {elevation:<9} {battery:<7} {count:<5} {seen_str:<12}\n"

    unique_digipeated_area.text = content
    # Optionally limit the number of displayed callsigns
    lines = unique_digipeated_area.text.split('\n')
    if len(lines) > 1001:  # 1000 data lines + headers
        unique_digipeated_area.text = '\n'.join(lines[:1001])


def refresh_beacons_area(beacons_dict, beacons_area):
    # Define column headers with specified widths
    headers = (
        f"{'Time':<20} "
        f"{'Destination':<20} "
        f"{'Path':<15} "
        f"{'Latitude':<10} "
        f"{'Longitude':<10} "
        f"{'Elevation':<10} "
        f"{'Battery':<7} "
        f"{'Comment':<40} "   # Increased width to 40
        f"{'Digipeated Via':<14} "
        f"{'Country':<7}\n"
    )
    separator = (
        f"{'-'*20} "
        f"{'-'*20} "
        f"{'-'*15} "
        f"{'-'*10} "
        f"{'-'*10} "
        f"{'-'*10} "
        f"{'-'*7} "
        f"{'-'*40} "        # Adjusted separator to match new width
        f"{'-'*14} "
        f"{'-'*7}\n"
    )
    content = headers + separator
    current_time = datetime.now()

    for beacon_id, data in reversed(beacons_dict.items()):
        try:
            time_diff = current_time - data['last_seen']
            seen_str = format_timedelta(time_diff)
            # Safely get each field with defaults
            time_field = data.get('Time') or 'N/A'
            destination = data.get('Destination') or 'N/A'
            path = data.get('Path') or 'N/A'
            path = str(path)  # Ensure path is a string
            latitude = data.get('Latitude') or 'N/A'
            longitude = data.get('Longitude') or 'N/A'
            elevation = data.get('Elevation') or 'N/A'
            battery = data.get('Battery') or 'N/A'
            comment = data.get('Comment') or 'N/A'
            digipeated_via = data.get('Digipeated_Via') or 'N/A'
            digipeated_via = str(digipeated_via)  # Ensure digipeated_via is a string
            country = data.get('Country') or 'N/A'

            content += (
                f"{time_field:<20} "
                f"{destination:<20} "
                f"{path:<15} "
                f"{latitude:<10} "
                f"{longitude:<10} "
                f"{elevation:<10} "
                f"{battery:<7} "
                f"{comment:<40} "   # Adjusted width to 40
                f"{digipeated_via:<14} "
                f"{country:<7}\n"
            )
        except Exception as e:
            print(f"Error processing beacon {beacon_id}: {e}")
            continue

    beacons_area.text = content
    # Optionally limit the number of displayed beacons
    lines = beacons_area.text.split('\n')
    if len(lines) > 1001:
        beacons_area.text = '\n'.join(lines[:1001])


def refresh_decoded_stations_area(decoded_stations_dict, decoded_stations_area):
    # Define column headers with specified widths
    headers = f"{'Time':<20} {'Callsign':<10} {'Destination':<20} {'Path':<15} {'SNR':<6} {'RSSI':<6} {'Latitude':<10} {'Longitude':<10} {'Elevation':<10} {'Distance':<8} {'Battery':<7} {'Comment':<20} {'Country':<7} {'Digipeated Via':<14}\n"
    separator = f"{'-'*20} {'-'*10} {'-'*20} {'-'*15} {'-'*6} {'-'*6} {'-'*10} {'-'*10} {'-'*10} {'-'*8} {'-'*7} {'-'*20} {'-'*7} {'-'*14}\n"
    content = headers + separator
    current_time = datetime.now()

    for station_id, data in reversed(decoded_stations_dict.items()):
        try:
            time_diff = current_time - data['last_seen']
            seen_str = format_timedelta(time_diff)
            # Safely get each field with defaults
            time_field = data.get('Time') or 'N/A'
            callsign = data.get('Callsign') or 'N/A'
            destination = data.get('Destination') or 'N/A'
            path = data.get('Path') or 'N/A'
            path = str(path)  # Ensure path is a string
            snr = data.get('SNR') or 'N/A'
            rssi = data.get('RSSI') or 'N/A'
            latitude = data.get('Latitude') or 'N/A'
            longitude = data.get('Longitude') or 'N/A'
            elevation = data.get('Elevation') or 'N/A'
            distance = data.get('Distance') or 'N/A'
            battery = data.get('Battery') or 'N/A'
            comment = data.get('Comment') or 'N/A'
            country = data.get('Country') or 'N/A'
            digipeated_via = data.get('Digipeated_Via') or 'N/A'
            digipeated_via = str(digipeated_via)  # Ensure digipeated_via is a string

            content += (
                f"{time_field:<20} "
                f"{callsign:<10} "
                f"{destination:<20} "
                f"{path:<15} "
                f"{snr:<6} "
                f"{rssi:<6} "
                f"{latitude:<10} "
                f"{longitude:<10} "
                f"{elevation:<10} "
                f"{distance:<8} "
                f"{battery:<7} "
                f"{comment:<20} "
                f"{country:<7} "
                f"{digipeated_via:<14}\n"
            )
        except Exception as e:
            print(f"Error processing decoded station {station_id}: {e}")
            continue

    decoded_stations_area.text = content
    # Optionally limit the number of displayed stations
    lines = decoded_stations_area.text.split('\n')
    if len(lines) > 1001:
        decoded_stations_area.text = '\n'.join(lines[:1001])


def format_timedelta(td):
    total_seconds = int(td.total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    parts = []
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0 or hours > 0:
        parts.append(f"{minutes}m")
    parts.append(f"{seconds}s")
    return ' '.join(parts)


async def update_seen_times(unique_direct_dict, unique_digipeated_dict, beacons_dict, decoded_stations_dict, unique_direct_area, unique_digipeated_area, beacons_area, decoded_stations_area, application):
    try:
        while True:
            refresh_unique_direct_area(unique_direct_dict, unique_direct_area)
            refresh_unique_digipeated_area(unique_digipeated_dict, unique_digipeated_area, unique_direct_dict)
            refresh_beacons_area(beacons_dict, beacons_area)
            refresh_decoded_stations_area(decoded_stations_dict, decoded_stations_area)
            await asyncio.sleep(1)  # Update every second
    except asyncio.CancelledError:
        # Task was cancelled
        pass
    except Exception as e:
        print(f"Error in update_seen_times: {e}")


async def fetch_igates():
    igates_set = set()
    tls_context = ssl.create_default_context()
    try:
        async with Client(
            hostname='hydros.link9.net',
            port=8183,
            transport='websockets',
            tls_context=tls_context,
        ) as client:
            await client.subscribe('lora_aprs/#')

            messages = client.messages

            # Collect messages until no more messages come in for a certain time
            timeout = 1.0  # seconds
            while True:
                try:
                    message = await asyncio.wait_for(messages.__anext__(), timeout=timeout)
                    topic_parts = str(message.topic).split('/')  # Convert Topic to string
                    if len(topic_parts) >= 2:
                        igate = topic_parts[1]
                        if validate_callsign(igate):
                            igates_set.add(igate)
                except asyncio.TimeoutError:
                    # No more messages
                    break
    except Exception as e:
        print(f"Error fetching iGates via MQTT: {e}")
        return []
    else:
        igates = list(igates_set)
        igates.sort()  # Sort the iGates alphanumerically
        return igates


async def select_igate(igates, default=None):
    # Place "Enter Manually" at the top without a separator
    manual_entry_value = "__manual_entry__"

    igate_tuples = [
        (manual_entry_value, "Enter Manually")
    ] + [(igate, igate) for igate in igates]

    # Set default value if provided
    if default and default in igates:
        default_value = default
    else:
        default_value = manual_entry_value  # Set "Enter Manually" as default if no previous selection

    # Display the radiolist dialog
    igate = await radiolist_dialog(
        title="Select iGate",
        text="Please select an iGate or choose to enter manually:",
        values=igate_tuples,
        default=default_value  # Set default selection
    ).run_async()

    if igate == manual_entry_value:
        # Prompt user to enter a callsign manually
        while True:
            user_input = await input_dialog(
                title="Manual iGate Entry",
                text="Please enter the iGate callsign:"
            ).run_async()

            if user_input is None:
                # User cancelled the input dialog
                return None

            user_input = user_input.strip().upper()
            if validate_callsign(user_input):
                return user_input
            else:
                # Show an error message and prompt again
                await input_dialog(
                    title="Invalid Callsign",
                    text="The entered callsign is invalid. Please enter a valid callsign."
                ).run_async()
    else:
        return igate


def validate_callsign(callsign):
    """
    Validate the callsign format using the provided regex.
    This regex ensures:
    - At least two letters.
    - At least one digit.
    - 1 to 7 alphanumeric characters, optionally followed by a hyphen and 1 to 2 alphanumeric characters.
    """
    callsign_pattern_with_ssid = r"^(?=[^-]*\d)(?=(?:[^-]*[A-Za-z]){2,})[A-Za-z0-9]{1,7}(?:-[A-Za-z0-9]{1,2})?$"
    pattern = re.compile(callsign_pattern_with_ssid)
    return bool(pattern.match(callsign))


def get_style():
    return Style.from_dict({
        'header': 'bold underline',
        'instructions': 'italic',
        'logs': 'bg:#000000 #00ff00',
        'beacons': 'bg:#000000 #00ff00',
        'decoded': 'bg:#000000 #00ff00',
        'unique_direct': 'bg:#000000 #00ff00',
        'unique_digipeated': 'bg:#000000 #00ff00',
        'status_connected_dot': 'fg:green bold',       # Green dot for connected
        'status_connected_text': 'fg:green bold',      # Green text for connected
        'status_disconnected_dot': 'fg:red bold',      # Red dot for disconnected
        'status_disconnected_text': 'fg:red bold',     # Red text for disconnected
        'new_version': 'fg:red bold',                  # Red bold text for new version message
        # Optional: Style for "Enter Manually" to make it stand out
        'enter_manually': 'fg:cyan bold',              # Cyan bold text
    })


async def check_for_updates(current_version):
    url = 'https://raw.githubusercontent.com/madpsy/lora-aprs-python-client/refs/heads/main/VERSION'
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    latest_version = (await resp.text()).strip()
                    return latest_version != current_version
                else:
                    print(f"Failed to fetch latest version. Status code: {resp.status}")
                    return False
    except Exception as e:
        print(f"Error checking for updates: {e}")
        return False


if __name__ == '__main__':
        asyncio.run(main())

