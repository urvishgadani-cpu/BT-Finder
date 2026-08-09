[app]
title = BT Finder
package.name = btfinder
package.domain = org.btfinder
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,json
version = 1.0.0

requirements = python3,kivy==2.3.1,kivymd==1.2.0,bleak,plyer,requests,kivy_garden.mapview

android.permissions = INTERNET, BLUETOOTH, BLUETOOTH_ADMIN, BLUETOOTH_SCAN, BLUETOOTH_CONNECT, ACCESS_FINE_LOCATION, ACCESS_COARSE_LOCATION
android.api = 33
android.minapi = 21
android.ndk = 25b

orientation = portrait
fullscreen = 0