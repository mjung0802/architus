import json
import traceback
import asyncio
import secrets
import websockets
from discord.ext.commands import Cog, Context, MinimalHelpCommand


class MockMember(object):
    def __init__(self, id=0):
        self.id = id
        self.mention = "<@%_CLIENT_ID_%>"
        self.display_name = "bad guy"
class MockRole(object):
    pass

class MockChannel(object):
    def __init__(self, sends, reactions):
        self.sends = sends
        self.reactions = reactions
    async def send(self, *args):
        for thing in args:
            self.sends.append(thing)
        return MockMessage(0, self.sends, self.reactions, 0)

class MockGuild(object):
    def __init__(self, id):
        self.region = 'us-east'
        self.id = int(id)
        self.owner = MockMember()
        self.me = MockMember()
        self.default_role = MockRole()
        self.default_role.mention = "@everyone"
        self.emojis = []

    def get_member(self, *args):
        return None

class MockReact(object):
    def __init__(self, message, emoji, user):
        self.message = message
        self.emoji = emoji
        self.count = 1
        self.users = [user]

class MockMessage(object):
    def __init__(self, id, sends, reaction_sends, guild_id, content=None):
        self.id = id
        self.sends = sends
        self.reaction_sends = reaction_sends
        self._state = MockChannel(sends, reactions)
        self.guild = MockGuild(guild_id)
        self.author = MockMember()
        self.channel = MockChannel(sends, reactions)
        self.content = content
        self.reactions = []
    async def add_reaction(self, emoji, bot=True):
        user = MockMember()
        if bot:
            self.reaction_sends.append((self.id, emoji))
            user = self.bot
        for react in self.reactions:
            if emoji == react.emoji:
                react.users.append(user)
                return react
        else:
            react = MockReact(self, emoji, user)
            self.reactions.append(react)
            return react

class Api(Cog):

    def __init__(self, bot):
        self.bot = bot
        self.fake_messages = {}

    async def handle_socket(self, websocket, path):
        while True:
            try:
                try:
                    data = json.loads(await websocket.recv())
                    print("recv: " + str(data))
                    if data['_module'] == 'interpret':
                        resp = await self.interpret(**data)
                    else:
                        resp = {'content': "Unknown module"}
                except Exception as e:
                    traceback.print_exc()
                    print(f"caught {e} while handling websocket request")
                    resp = {'content': f"caught {e} while handling websocket request"}
                await websocket.send(json.dumps(resp))
            except websockets.exceptions.ConnectionClosed:
                print("Websocket connection closed")
                return

    @asyncio.coroutine
    def handle_request(self, pub, msg):
        try:
            resp = json.dumps((yield from getattr(self, msg['method'])(*msg['args'])))
        except Exception as e:
            traceback.print_exc()
            print(f"caught {e} while handling {msg['topic']}s request")
            resp = '{"message": "' + str(e) + '"}'
        yield from pub.send((str(msg['topic']) + ' ' + str(resp)).encode())

    async def fetch_user_dict(self, id):
        usr = await self.bot.fetch_user(int(id))
        return {'name': usr.name, 'avatar': usr.avatar}

    async def reload_extension(self, extension_name):
        name = extension_name.replace('-', '.')
        print(f"reloading extention: {name}")
        self.bot.reload_extension(name)
        return {}

    async def interpret(self, guild_id=None, content=None, message_id=None, added_reactions=None, allowed_commands=None, silent=False, **k):
        sends = []
        reactions = []
        edit = False

        if content:
            # search for builtin commands
            command = None
            args = content.split()
            possible_commands = [cmd for cmd in self.bot.commands if cmd.name in allowed_commands]
            for cmd in possible_commands:
                if args[0][1:] in cmd.aliases + [cmd.name]:
                    command = cmd
                    break

            mock_message = MockMessage(message_id, sends, reactions, guild_id, content=content)
            mock_channel = MockChannel(sends, reactions)

            self.bot.user_commands.setdefault(int(guild_id), [])
            if command:
                # found builtin command, creating fake context
                ctx = Context(**{
                    'message': mock_message,
                    'bot': self.bot,
                    'args': args[1:],
                    'prefix': content[0],
                    'command': command,
                    'invoked_with': args[0]
                })
                ctx.send = lambda content: sends.append(content)
                await ctx.invoke(command, *args[1:])
            elif args[0][1:] == 'help':
                help_text = ''
                for cmd in possible_commands:
                    try:
                        if args[1] in cmd.aliases or args[1] == cmd.name:
                            help_text += f'```{args[1]} - {cmd.help}```'
                            break
                    except IndexError:
                        help_text += '```{}: {:>5}```\n'.format(cmd.name, cmd.help)
                        
                sends.append(help_text)
            else:
                # check for user set commands in this "guild"
                for command in self.bot.user_commands[mock_message.guild.id]:
                    if (command.triggered(mock_message.content)):
                        await command.execute(mock_message, self.bot.session)
                        break

            # Prevent response sending for silent requests
            if silent:
                sends = ()

            resp_id = secrets.randbits(24) | 1 if sends else None
        elif added_reactions:
            edit = True
            for react in added_reactions:
                fkmsg = self.fake_messages[guild_id][react[0]]
                fkmsg.sends = sends
                react = fkmsg.add_reaction(react[1], bot=False)
                self.bot.get_cog("EventCog").on_reaction_add(react, MockMember())
        elif removed_reactions:
            pass
        resp = {
            '_module': 'interpret',
            'content': '\n'.join(sends),
            'added_reactions': [(resp_id if r[0] == 0 else message_id, r[1]) for r in reactions],
            'message_id': resp_id,
            'edit': edit,
            'guild_id': guild_id,
        }
        if resp['content']:
            print(resp)
        return resp


def setup(bot):
    bot.add_cog(Api(bot))
