import asyncio
import aiomqtt

#https://pypi.org/project/renogy-modbus-lib-python/#:~:text=RenogyBT%20for%20Python%20SDK
from renogy_lib_python.modbus_comm import EnhancedModbusClient
import paho.mqtt.client as mqtt

def merge_list_of_dicts(ld):
    out = {}
    for d in ld:
        out = out | d
    return out

async def main():
    async with aiomqtt.Client("localhost") as mqtt_client:
        client = EnhancedModbusClient(slave_address=0xFF) 
        connected = False
        choices = ["battery","controller"]
        try:
            #devices = await client.scan_devices()
            success = await client.connect('D8:B6:73:BE:8F:BF')#'E8:FD:F8:D8:31:8F'
            connected = success
            if success:
                while True:
                    data = await client.get_hole_original_data(DeviceType='controller')
                    status = await client.get_status(DeviceType='controller')
                    #print(data)
                    #print(status)
                    all = merge_list_of_dicts(data) | merge_list_of_dicts(status)
                    #print(all)
                    for k, v in all.items():
                        await mqtt_client.publish(f"12v/{k}", payload=v)



                    
        except Exception as e:
            print(f"catch exception:{str(e)}")
        finally:
            if connected:
                await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
