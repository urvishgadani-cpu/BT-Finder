import asyncio
import threading
import json
import os
import webbrowser
import requests
from datetime import datetime

from kivy.app import App
from kivy.lang import Builder
from kivy.clock import Clock
from kivy.uix.screenmanager import ScreenManager, Screen
from kivymd.app import MDApp
from kivymd.uix.list import TwoLineIconListItem, IconLeftWidget
from kivymd.uix.dialog import MDDialog
from kivymd.uix.button import MDFlatButton, MDRaisedButton
from kivy_garden.mapview import MapView, MapMarker

from bleak import BleakScanner
from plyer import gps

MEMORY_FILE = "last_known_locations.json"
SAVED_DEVICES_FILE = "saved_devices.json"

def load_json(filename):
    if os.path.exists(filename):
        try:
            with open(filename, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_json(filename, data):
    try:
        with open(filename, "w") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        print(f"Error saving {filename}: {e}")

LAST_KNOWN_LOCATIONS = load_json(MEMORY_FILE)
SAVED_DEVICES = load_json(SAVED_DEVICES_FILE)

KV = '''
ScreenManager:
    LoginScreen:
    DeviceListScreen:
    DeviceDetailScreen:

<LoginScreen>:
    name: 'login'
    MDFloatLayout:
        MDCard:
            size_hint: None, None
            size: "320dp", "400dp"
            pos_hint: {"center_x": 0.5, "center_y": 0.5}
            elevation: 4
            padding: "20dp"
            spacing: "15dp"
            orientation: 'vertical'

            MDLabel:
                text: "BT Finder Pro"
                font_style: "H4"
                halign: "center"
                bold: True

            MDTextField:
                id: email
                hint_text: "Email"
                icon_right: "email"

            MDTextField:
                id: password
                hint_text: "Password"
                password: True
                icon_right: "key"

            MDRaisedButton:
                text: "LOGIN"
                pos_hint: {"center_x": 0.5}
                on_release: root.manager.current = 'device_list'

            MDFlatButton:
                text: "Continue as Guest"
                pos_hint: {"center_x": 0.5}
                on_release: root.manager.current = 'device_list'

<DeviceListScreen>:
    name: 'device_list'
    MDBoxLayout:
        orientation: 'vertical'

        MDTopAppBar:
            title: "BT Finder - Devices"
            right_action_items: [["refresh", lambda x: root.trigger_manual_scan()]]

        MDScrollView:
            MDList:
                id: device_container

<DeviceDetailScreen>:
    name: 'device_detail'
    MDBoxLayout:
        orientation: 'vertical'

        MDTopAppBar:
            title: "Device Radar & GPS"
            left_action_items: [["arrow-left", lambda x: app.go_back()]]

        MDBoxLayout:
            id: map_container
            size_hint_y: 0.45

        MDBoxLayout:
            orientation: 'vertical'
            size_hint_y: 0.55
            padding: "15dp"
            spacing: "6dp"

            MDLabel:
                id: dev_name
                text: "Device Name"
                font_style: "H6"

            MDLabel:
                id: dev_address
                text: "Address: --"
                theme_text_color: "Secondary"

            MDLabel:
                id: dev_rssi
                text: "Live RSSI: -- dBm"

            MDLabel:
                id: dev_trend
                text: "Proximity Trend: Calculating..."
                theme_text_color: "Primary"
                bold: True

            MDLabel:
                id: last_seen
                text: "GPS Location: Fetching..."
                theme_text_color: "Hint"

            MDBoxLayout:
                orientation: 'horizontal'
                spacing: "8dp"
                pos_hint: {"center_x": 0.5}

                MDRaisedButton:
                    id: fav_btn
                    text: "Save as Favorite"
                    icon: "star"
                    on_release: root.toggle_favorite()

                MDRaisedButton:
                    text: "Google Maps"
                    icon: "google-maps"
                    on_release: root.open_in_google_maps()

                MDFlatButton:
                    text: "Chime"
                    on_release: root.play_sound()
'''

class LoginScreen(Screen):
    pass

class DeviceListScreen(Screen):
    auto_refresh_event = None

    def on_enter(self):
        self.trigger_manual_scan()
        if not self.auto_refresh_event:
            self.auto_refresh_event = Clock.schedule_interval(lambda dt: self.trigger_manual_scan(), 4.0)

    def on_leave(self):
        if self.auto_refresh_event:
            self.auto_refresh_event.cancel()
            self.auto_refresh_event = None

    def trigger_manual_scan(self):
        threading.Thread(target=self._run_ble_scan, daemon=True).start()

    def _run_ble_scan(self):
        async def scan():
            try:
                devices = await BleakScanner.discover(timeout=3.0)
                Clock.schedule_once(lambda dt: self.update_list(devices))
            except Exception as e:
                print(f"BLE Scan Error: {e}")

        asyncio.run(scan())

    def update_list(self, devices):
        container = self.ids.device_container
        container.clear_widgets()

        if not devices:
            item = TwoLineIconListItem(
                text="Scanning for Bluetooth devices...",
                secondary_text="Ensure Bluetooth and Location are enabled"
            )
            container.add_widget(item)
            return

        for d in devices:
            raw_name = d.name.strip() if d.name else ""
            mac = d.address
            
            # Match against saved favorite names
            if mac in SAVED_DEVICES:
                display_name = f"★ {SAVED_DEVICES[mac]}"
            elif raw_name:
                display_name = raw_name
            else:
                addr_short = mac.replace(":", "")[-4:]
                display_name = f"Bluetooth Peripheral [{addr_short}]"

            rssi = getattr(d, 'rssi', 'N/A')

            item = TwoLineIconListItem(
                text=display_name,
                secondary_text=f"Address: {mac} | Signal: {rssi} dBm",
                on_release=lambda x, dev=d, name=display_name: self.open_detail(dev, name)
            )
            item.add_widget(IconLeftWidget(icon="star" if mac in SAVED_DEVICES else "bluetooth"))
            container.add_widget(item)

    def open_detail(self, device, display_name):
        app = MDApp.get_running_app()
        app.selected_device = device
        app.selected_device_name = display_name
        self.manager.current = 'device_detail'

class DeviceDetailScreen(Screen):
    dialog = None
    current_lat = None
    current_lon = None
    previous_rssi = None

    def on_enter(self):
        app = MDApp.get_running_app()
        dev = getattr(app, 'selected_device', None)
        dev_name = getattr(app, 'selected_device_name', 'Bluetooth Device')

        if dev:
            rssi = getattr(dev, 'rssi', None)
            self.ids.dev_name.text = f"Device: {dev_name}"
            self.ids.dev_address.text = f"Address: {dev.address}"
            
            # Calculate RSSI trend (Warmer / Colder)
            if rssi is not None:
                self.ids.dev_rssi.text = f"Live Signal (RSSI): {rssi} dBm"
                if self.previous_rssi is not None:
                    delta = rssi - self.previous_rssi
                    if delta > 2:
                        self.ids.dev_trend.text = "Proximity Trend: 🔥 Getting Warmer (Closer)"
                    elif delta < -2:
                        self.ids.dev_trend.text = "Proximity Trend: ❄️ Getting Colder (Farther)"
                    else:
                        self.ids.dev_trend.text = "Proximity Trend: ↔️ Steady Distance"
                self.previous_rssi = rssi

            # Update favorite button status
            if dev.address in SAVED_DEVICES:
                self.ids.fav_btn.text = "Unfavorite"
            else:
                self.ids.fav_btn.text = "Save as Favorite"

            threading.Thread(target=self._get_location, args=(dev.address,), daemon=True).start()

    def toggle_favorite(self):
        app = MDApp.get_running_app()
        dev = getattr(app, 'selected_device', None)
        if dev:
            mac = dev.address
            if mac in SAVED_DEVICES:
                del SAVED_DEVICES[mac]
                self.ids.fav_btn.text = "Save as Favorite"
            else:
                clean_name = dev.name if dev.name else f"My Device [{mac[-4:]}]"
                SAVED_DEVICES[mac] = clean_name
                self.ids.fav_btn.text = "Unfavorite"
            
            save_json(SAVED_DEVICES_FILE, SAVED_DEVICES)

    def _get_location(self, mac_address):
        timestamp = datetime.now().strftime("%Y-%m-%d %I:%M %p")
        
        # 1. Try Hardware GPS via Plyer
        try:
            gps.configure(on_location=self._on_gps_location)
            gps.start(minTime=1000, minDistance=1)
        except Exception:
            # 2. Fallback to IP Network Geolocation
            try:
                res = requests.get("https://ipapi.co/json/", timeout=4).json()
                lat = res.get("latitude")
                lon = res.get("longitude")
                city = res.get("city", "Local Region")

                if lat and lon:
                    self._record_and_render_location(mac_address, lat, lon, city, timestamp)
                    return
            except Exception as e:
                print(f"Location fetch failed: {e}")

        # 3. Fallback to cached history
        if mac_address in LAST_KNOWN_LOCATIONS and LAST_KNOWN_LOCATIONS[mac_address]:
            history = LAST_KNOWN_LOCATIONS[mac_address]
            latest = history[-1]
            self.current_lat = latest["lat"]
            self.current_lon = latest["lon"]
            Clock.schedule_once(lambda dt: self._render_map(
                latest["lat"], latest["lon"], latest["location_name"], f"Last Seen: {latest['timestamp']}"
            ))

    def _on_gps_location(self, **kwargs):
        app = MDApp.get_running_app()
        dev = getattr(app, 'selected_device', None)
        if dev:
            lat = kwargs.get('lat')
            lon = kwargs.get('lon')
            timestamp = datetime.now().strftime("%Y-%m-%d %I:%M %p")
            self._record_and_render_location(dev.address, lat, lon, "Hardware GPS Position", timestamp)

    def _record_and_render_location(self, mac_address, lat, lon, loc_name, timestamp):
        if mac_address not in LAST_KNOWN_LOCATIONS:
            LAST_KNOWN_LOCATIONS[mac_address] = []

        history = LAST_KNOWN_LOCATIONS[mac_address]
        history.append({
            "lat": lat,
            "lon": lon,
            "location_name": loc_name,
            "timestamp": timestamp
        })

        # Maintain last 20 sightings
        if len(history) > 20:
            history.pop(0)

        save_json(MEMORY_FILE, LAST_KNOWN_LOCATIONS)

        self.current_lat = lat
        self.current_lon = lon
        Clock.schedule_once(lambda dt: self._render_map(lat, lon, loc_name, f"Recorded at {timestamp}"))

    def _render_map(self, lat, lon, loc_str, time_str):
        self.ids.map_container.clear_widgets()

        mapview = MapView(zoom=15, lat=lat, lon=lon)
        marker = MapMarker(lat=lat, lon=lon)
        mapview.add_marker(marker)

        self.ids.map_container.add_widget(mapview)
        self.ids.last_seen.text = f"{loc_str}\n({time_str})"

    def open_in_google_maps(self):
        if self.current_lat and self.current_lon:
            url = f"https://www.google.com/maps/search/?api=1&query={self.current_lat},{self.current_lon}"
            webbrowser.open(url)

    def play_sound(self):
        if not self.dialog:
            self.dialog = MDDialog(
                title="Locate Chime",
                text="Emitting audio signal to locate target Bluetooth accessory...",
                buttons=[MDFlatButton(text="DISMISS", on_release=lambda x: self.dialog.dismiss())]
            )
        self.dialog.open()

class BTFinderApp(MDApp):
    selected_device = None
    selected_device_name = None

    def build(self):
        self.theme_cls.primary_palette = "Blue"
        return Builder.load_string(KV)

    def go_back(self):
        self.root.current = 'device_list'

if __name__ == '__main__':
    BTFinderApp().run()