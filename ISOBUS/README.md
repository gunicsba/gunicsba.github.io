# Hardware needed:

## PEAK PCAN

Or some 10$ aliexpress PCAN adapter clone:
https://www.aliexpress.com/item/1005006000190091.html

You'll need the official driver:
https://www.peak-system.com/Drivers.523.0.html?&L=1

## RS232 adapter (to steal GPS data from tractor)
https://www.aliexpress.com/item/1005006026595453.html

Driver:  (in case windows update doesn't do its job)
https://ftdichip.com/wp-content/uploads/2025/03/CDM2123620_Setup.zip



If TC doesn't start in Agio Settings -> ISOBUS:

C:\"Program Files"\AOG-TaskController\bin\AOG-TaskController.exe --can_adapter=PEAK-PCAN --can_channel=2 --log_level=debug --log2file

VT is always adapter 1

so TC could be adapter 2 or if you have 2 tablets then it'll be adapter 1.



If multiple TC is present we're #0 so make sure others claim their numbers higher.



