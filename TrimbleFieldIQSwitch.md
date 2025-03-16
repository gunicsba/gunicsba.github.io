# TrimbleFieldIQ Switch panel

Baud rate: 250k

CAN messages:
### Sent only at startup:
18EAFFE4

18EBFFE4

18EEFFE4

### Sent regularly at 2Hz frequency:
18FFC1E4 

18FFC4E4 Section and main Switch:

 * 7.0 -> main switch on/off
 * 6.7 -> 1st section
 * 6.6 -> 2nd section
 * ...
 * 6.0 -> 8th section
 * 7.7 -> 9th section
 * 7.6 -> 10th section

18FFD8E4

18FFD9E4

### Sent on-demand (i.e when we move the button)
18FFC7E4 1/2/M toggle switch
 * 0.6 + 0.7:
 * 00 -> mode 1
 * 01 -> mode 2
  10 -> mode M
  0.4 -> rate UP
  0.3 -> rate down
