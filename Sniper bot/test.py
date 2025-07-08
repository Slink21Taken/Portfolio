import discord
import asyncio

TOKEN ="MTM4ODk2OTUyMDc4OTcyMTM2OQ.GrTCL8.FoXLN51O0n8DEwL8L_IipyeBUaOsgJMIH5GMaI"
CHANNEL_ID =1389318386244390934  # Replace with your channel ID

intents = discord.Intents.default()
client = discord.Client(intents=intents)

async def send_terminal_messages():
    await client.wait_until_ready()
    channel = client.get_channel(CHANNEL_ID)

    if not channel:
        print("Channel not found.")
        return

    print("Ready! Type a message to send to Discord:")

    while True:
        msg = input("> ")  # This runs in a blocking way
        await channel.send(msg)

@client.event
async def on_ready():
    print(f"Logged in as {client.user}")
    client.loop.create_task(send_terminal_messages())

client.run(TOKEN)
