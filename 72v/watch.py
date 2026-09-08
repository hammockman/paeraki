# jh@sing:~/paeraki/72v $ python service_explorer.py --address A4:C1:37:14:70:77
# 2026-02-25 08:55:55,278 __main__ INFO: starting scan...
# 2026-02-25 08:55:56,306 __main__ INFO: connecting to device...
# 2026-02-25 08:56:00,369 __main__ INFO: connected to  (A4:C1:37:14:70:77)

# 2026-02-25 08:56:00,369 __main__ INFO: [Service] 00001801-0000-1000-8000-00805f9b34fb (Handle: 8): Generic Attribute Profile
# 2026-02-25 08:56:00,370 __main__ INFO:   [Characteristic] 00002a05-0000-1000-8000-00805f9b34fb (Handle: 9): Service Changed (indicate)
# 2026-02-25 08:56:00,370 __main__ ERROR:     [Descriptor] 00002902-0000-1000-8000-00805f9b34fb (Handle: 11): Client Characteristic Configuration, Error: Descriptor with handle 00002902-0000-1000-8000-00805f9b34fb (Handle: 11): Client Characteristic Configuration was not found!

# 2026-02-25 08:56:00,370 __main__ INFO: [Service] 0000180a-0000-1000-8000-00805f9b34fb (Handle: 12): Device Information
# 2026-02-25 08:56:00,810 __main__ INFO:   [Characteristic] 00002a50-0000-1000-8000-00805f9b34fb (Handle: 13): PnP ID (read), Value: bytearray(b'\x02\x8a$f\x82\x01\x00')

# 2026-02-25 08:56:00,811 __main__ INFO: [Service] 0000ff00-0000-1000-8000-00805f9b34fb (Handle: 15): Vendor specific
# 2026-02-25 08:56:00,886 __main__ INFO:   [Characteristic] 0000ff02-0000-1000-8000-00805f9b34fb (Handle: 20): Vendor specific (read,write-without-response), Value: bytearray(b'\xdd\xa5\xfa\x03\x00\x1d\x01\xfe\xe5w\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'), Max write w/o rsp size: 20
# 2026-02-25 08:56:00,886 __main__ ERROR:     [Descriptor] 00002901-0000-1000-8000-00805f9b34fb (Handle: 22): Characteristic User Description, Error: Descriptor with handle 00002901-0000-1000-8000-00805f9b34fb (Handle: 22): Characteristic User Description was not found!
# 2026-02-25 08:56:01,036 __main__ INFO:   [Characteristic] 0000ff01-0000-1000-8000-00805f9b34fb (Handle: 16): Vendor specific (read,notify), Value: bytearray(b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00')
# 2026-02-25 08:56:01,036 __main__ ERROR:     [Descriptor] 00002901-0000-1000-8000-00805f9b34fb (Handle: 19): Characteristic User Description, Error: Descriptor with handle 00002901-0000-1000-8000-00805f9b34fb (Handle: 19): Characteristic User Description was not found!
# 2026-02-25 08:56:01,036 __main__ ERROR:     [Descriptor] 00002902-0000-1000-8000-00805f9b34fb (Handle: 18): Client Characteristic Configuration, Error: Descriptor with handle 00002902-0000-1000-8000-00805f9b34fb (Handle: 18): Client Characteristic Configuration was not found!

# 2026-02-25 08:56:01,036 __main__ INFO: [Service] 0000fa00-0000-1000-8000-00805f9b34fb (Handle: 23): Vendor specific
# 2026-02-25 08:56:01,148 __main__ INFO:   [Characteristic] 0000fa01-0000-1000-8000-00805f9b34fb (Handle: 24): Vendor specific (read,write-without-response,notify), Value: bytearray(b'\x00'), Max write w/o rsp size: 20
# 2026-02-25 08:56:01,148 __main__ ERROR:     [Descriptor] 00002901-0000-1000-8000-00805f9b34fb (Handle: 26): Characteristic User Description, Error: Descriptor with handle 00002901-0000-1000-8000-00805f9b34fb (Handle: 26): Characteristic User Description was not found!
# 2026-02-25 08:56:01,148 __main__ ERROR:     [Descriptor] 11120010-fa01-0019-1600-290100132901 (Handle: 27): Unknown, Error: Descriptor with handle 11120010-fa01-0019-1600-290100132901 (Handle: 27): Unknown was not found!
# 2026-02-25 08:56:01,148 __main__ INFO: disconnecting...
# 2026-02-25 08:56:03,737 __main__ INFO: disconnected


#Bluetooth UUID
#SERVICE UUID: 0000ff00-0000-1000-8000-00805f9b34fb
#write characteristic UUID: 0000ff02-0000-1000-8000-00805f9b34fb
#read characteristic UUID:


import asyncio
import aiomqtt
import paho.mqtt.client as mqtt
import time
from bleak import BleakClient



def parse_response(sender, data):
    print('***', data.decode())


async def get_jbd_bms_registers(addr):
    cuid_write = "0000ff02-0000-1000-8000-00805f9b34fb"
    cuid_read = "0000ff01-0000-1000-8000-00805f9b34fb"

    async with BleakClient(addr) as client:
        #if client.is_connected:
        print(f"Connected: {client.is_connected}")
        await client.start_notify(cuid_read, parse_response)
        await asyncio.sleep(1)
        await client.write_gatt_char(cuid_write, b'\xdd\xa5\x03\x00\xff\xfd\x77', response=False)

        while True:
            print(await client.read_gatt_char(cuid_read))


        #else:
        #print("failed to connect")
        #res = await client.read_gatt_char(cuid_read)
        #print(res)


        # Keep the connection alive to receive notifications (adjust as needed)
        await asyncio.sleep(60)

        # Stop notifications before disconnecting
        await client.stop_notify(cuid_read)



    return {}


async def main():
    async with aiomqtt.Client("192.168.1.1") as mqtt_client:
        while True:
            try:
                all = await get_jbd_bms_registers("A4:C1:37:14:70:77")
            except Exception as err:
                print(err)
            else:
                for k, v in all.items():
                    await mqtt_client.publish(f"72v/{k}", payload=v)
            time.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())
