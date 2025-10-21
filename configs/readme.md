F9P:
https://github.com/lansalot/AOGConfigOMatic/releases

Rename the downloaded files as Single.txt and it should be simple to flash.



How to easily modify RS232 on the UM982:

list COM ports
 > mode

change COM speed:  
 > mode com42 baud=115200 parity=n data=8 stop=1 

https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/mode


We can send commands like this:
 > echo command > PORT

Change to NMEA0183 V3 and change speed:
 > echo CONFIG NMEA0183 V31 > \\.\COM20  
 > echo CONFIG COM2 57600 > \\.\COM20  
 > echo SAVECONFIG > \\.\COM20  

Realterm v3 download:
https://www.i2cchip.com/realterm/Realterm_3.0.1.43_setup.exe
