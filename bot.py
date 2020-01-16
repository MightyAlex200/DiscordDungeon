import typing
from enum import Enum
import re
import concurrent.futures
import asyncio

from generator.gpt2.gpt2_generator import *
from story import grammars
from story.story_manager import *
from story.utils import *

import discord
from discord.ext import commands
from discord.ext.commands import CommandNotFound, guild_only

pool = concurrent.futures.ThreadPoolExecutor()


class GameMode(Enum):
    @classmethod
    async def convert(cls, ctx, arg):
        arg = arg.lower()
        if arg == "anarchy":
            return cls.Anarchy
        elif arg == 'ordered':
            return cls.Ordered
        raise Exception(f'Not a gamemode {arg}')

    @classmethod
    def str(cls, i: int):
        if i == cls.Anarchy:
            return 'Anarchy'
        elif i == cls.Ordered:
            return 'Ordered'
        raise Exception(f'Not a gamemode {i}')

    Anarchy = 0
    Ordered = 1


class Visibility(Enum):
    @classmethod
    async def convert(cls, ctx, arg):
        arg = arg.lower()
        if arg == "public":
            return cls.Public
        elif arg == "publiclocked":
            return cls.PublicLocked
        elif arg == "private":
            return cls.Private
        raise Exception(f'Not a visibility {arg}')

    @classmethod
    def str(cls, i: int):
        if i == cls.Public:
            return "Public"
        elif i == cls.PublicLocked:
            return "PublicLocked"
        elif i == cls.Private:
            return "Private"
        raise Exception(f'Not a visibility {i}')

    Public = 0  # TODO
    PublicLocked = 1  # TODO
    Private = 2


def create_story_manager(game):
    # blocking
    generator = GPT2Generator(censor=False)
    story_manager = UnconstrainedStoryManager(generator)
    res = story_manager.start_new_story(
        game.prompt, context="", upload_story=False
    )
    return (story_manager, res)


class Game:
    def __init__(self, owner, channel):
        self._queue = []
        self.owner = owner
        self.nsfw = False
        self.channel = channel
        self.visibility = Visibility.Private
        self.players = [owner]
        self.player_idx = 0
        self.started = False
        self.gamemode = GameMode.Ordered
        self.vote_kick = False
        self.vote_revert = False
        self.vote_retry = False
        self.story_manager = None
        self.prompt = None
        self.timeout = 90
        self.calculating = False

    async def initialize_story_manager(self):
        loop = asyncio.get_event_loop()
        (sm, res) = await loop.run_in_executor(
            pool, create_story_manager, self)
        self.story_manager = sm
        return res

    async def consume_queue(self):
        self.calculating = True
        to_calc = self._queue.pop(0)
        if to_calc:
            loop = asyncio.get_event_loop()
            try:
                res = await asyncio.wait_for(loop.run_in_executor(
                    pool, self.story_manager.act, f'\n> {to_calc[0]} {to_calc[1]}.\n'), self.timeout, loop=loop)
                await self.channel.send(
                    discord.utils.escape_mentions(
                        discord.utils.escape_markdown(
                            f'> {to_calc[0]} {to_calc[1]}.\n{res}')))
            except asyncio.TimeoutError:
                await self.channel.send('TIMEOUT REACHED. OPERATION CANCELLED')
            self.player_idx += 1
            self.player_idx %= len(self.players)
            if len(self._queue) > 0:
                await self.consume_queue()
            else:
                mem = self.channel.guild.get_member(
                    self.players[self.player_idx])
                if mem:
                    await self.channel.send(f'{mem.mention}\'s TURN')
        self.calculating = False

    async def add_to_queue(self, player, msg):
        if self.gamemode == GameMode.Ordered:
            if self.players[self.player_idx] == player.id:
                self._queue.append((player.display_name, msg))
                if not self.calculating:
                    await self.consume_queue()
        elif self.gamemode == GameMode.Anarchy:
            self._queue.append((player.display_name, msg))
            if not self.calculating:
                await self.consume_queue()
        else:
            raise Exception('Gamemode is out of bounds')


# TODO: persist this
# ChannelId -> Game
channel_games = dict()

bot = commands.Bot(command_prefix='!')

# game
#  x create
#  x start
#  x stop
#  x invite
#  x config
#    x give
#    x nsfw
#    x visibility
#    x gamemode
#    x prompt
#    x timeout
#    x votable
#      x kick
#      x revert
#      x retry
#  x delete
#  x list
# cmd
#  TODO: Voting
#  = revert
#  = kick
#  - insert
#  - retry


def get_game_channels(guild: discord.Guild):
    accepted_categories = ['lobbies', 'archived']
    return [chan for cat in guild.categories if cat.name in accepted_categories for chan in cat.text_channels]


def is_valid_game_name(ctx, name):
    return name and \
        len(name) <= 100 and \
        re.match('^[0-9a-z-_]+$', name) and \
        (not any(map(lambda chan: chan.name == name, get_game_channels(ctx.guild))))


def generate_valid_game_name(ctx):
    counter = 0
    while True:
        counter += 1
        name = f'{cleanse(ctx.author.display_name)}s-game-{counter}'
        if is_valid_game_name(ctx, name):
            return name


def valid_game_name(ctx, name):
    if is_valid_game_name(ctx, name):
        return name
    else:
        return generate_valid_game_name(ctx)


@bot.group()
async def game(ctx):
    """Manage your games"""
    if ctx.invoked_subcommand is None:
        raise CommandNotFound()


def cleanse(s):
    return re.sub('[^0-9a-z-_]', '-', s.lower().replace(' ', '-'))


@guild_only()
@game.command()
async def create(ctx, *, name: typing.Optional[str]):
    """Create a game"""
    if name:
        name = cleanse(name)
        if not is_valid_game_name(ctx, name):
            await ctx.send("INVALID GAME NAME, DEFAULTING")
    name = valid_game_name(ctx, name)
    overwrites = {
        ctx.guild.default_role: discord.PermissionOverwrite(read_messages=False),
        ctx.guild.me: discord.PermissionOverwrite(read_messages=True),
        ctx.guild.get_member(ctx.author.id): discord.PermissionOverwrite(read_messages=True)
    }
    category = next(
        cat for cat in ctx.guild.categories if cat.name == 'lobbies')
    channel = await ctx.guild.create_text_channel(name, overwrites=overwrites, category=category)
    channel_games[channel.id] = Game(ctx.author.id, channel)
    await ctx.send(f'CREATED CHANNEL {channel.mention}')
    await channel.send(f'{ctx.author.mention}, THIS IS YOUR NEW GAME LOBBY')
    await channel.send('USE THE COMMAND `GAME CONFIG` TO SEE AND CONTROL THE CONFIGURATION OF THIS GAME')
    await channel.send('ALSO SEE `HELP GAME CONFIG`')


@guild_only()
@game.command()
async def invite(ctx, player: typing.Union[discord.Member, discord.Role], chan: typing.Optional[discord.TextChannel]):
    """Invite a player to a game"""
    chan = owned_game_channel(ctx, chan)
    game = channel_games[chan.id]

    async def add_player(p):
        if player.id == bot.user.id:
            return await ctx.send('CANNOT ADD THIS BOT AS PARTICIPANT')
        game.players.append(player.id)
        await chan.set_permissions(player, read_messages=True)

    if isinstance(player, discord.Member):
        await add_player(player)
    else:
        for p in player.members:
            await add_player(p)

    await ctx.send('PLAYER(S) ADDED TO GAME')


@guild_only()
@game.command()
async def start(ctx, chan: typing.Optional[discord.TextChannel]):
    """Start a game"""
    chan = owned_game_channel(ctx, chan)
    game = channel_games[chan.id]
    if game.prompt:
        response = None
        if game.story_manager is None:
            await ctx.send('INITIALIZING AI DUNGEON. THIS MAY TAKE SOME TIME.')
            response = await game.initialize_story_manager()
            await ctx.send('INITIALIZATION COMPLETE.')
        game.started = True
        await ctx.send('GAME STARTED')
        if response:
            await ctx.send(response)
        await ctx.send(f'{ctx.guild.get_member(game.players[game.player_idx]).mention.upper()}, IT IS YOUR TURN')
    else:
        await ctx.send('PROMPT REQUIRED')


@guild_only()
@game.command()
async def stop(ctx, chan: typing.Optional[discord.TextChannel]):
    """Stop a game"""
    chan = owned_game_channel(ctx, chan)
    game = channel_games[chan.id]
    game.started = False
    if game.story_manager:
        game.story_manager = None
    await ctx.send('GAME STOPPED')


@guild_only()
@game.command()
async def list(ctx):
    """List your lobbies"""
    res = 'YOUR GAMES:\n'
    any_exist = False
    for chan in get_game_channels(ctx.guild):
        if chan.id in channel_games and channel_games[chan.id].owner == ctx.author.id:
            res += f'- {chan.mention}\n'
            any_exist = True
    if any_exist:
        await ctx.send(res)
    else:
        await ctx.send('YOU HAVE NO GAME LOBBIES')


@guild_only()
@game.command()
async def delete(ctx, chan: typing.Optional[discord.TextChannel]):
    """Delete one of your games"""
    chan = owned_game_channel(ctx, chan)
    if chan.id in channel_games and channel_games[chan.id].owner == ctx.author.id:
        channel_games.pop(chan.id)
        await chan.delete()
        if not ctx.channel == chan:
            await ctx.send('GAME DELETED')
        return
    await ctx.send('YOU DO NOT HAVE AUTHORIZIATION TO DELETE THIS CHANNEL')


@game.group()
async def config(ctx):
    """Configure your games"""
    if ctx.invoked_subcommand is None:
        raise CommandNotFound()


class GameChannelInvalidOrNotOwnedException(Exception):
    pass


def owned_game_channel(ctx, chan: typing.Optional[discord.TextChannel]):
    if chan:
        if chan.id in channel_games and channel_games[chan.id].owner == ctx.author.id:
            return chan
    else:
        return owned_game_channel(ctx, ctx.channel)
    raise GameChannelInvalidOrNotOwnedException


@guild_only()
@config.command()
async def give(ctx, user: discord.Member, chan: typing.Optional[discord.TextChannel]):
    """Transfer ownership of a game"""
    chan = owned_game_channel(ctx, chan)
    channel_games[chan.id].owner = user.id
    await ctx.send('OWNERSHIP TRANSFERED')


@guild_only()
@config.command()
async def nsfw(ctx, nsfw: typing.Optional[bool], chan: typing.Optional[discord.TextChannel]):
    """Set NSFW status of a game"""
    chan = owned_game_channel(ctx, chan)
    game = channel_games[chan.id]
    if nsfw is not None:
        game.nsfw = nsfw
        await chan.edit(nsfw=nsfw)
        await ctx.send('NSFW STATUS UPDATED')
    else:
        await ctx.send(f'NSFW STATUS IS {str(game.nsfw).upper()}')


@guild_only()
@config.command()
async def visibility(ctx, visibility: typing.Optional[Visibility], chan: typing.Optional[discord.TextChannel]):
    """Set visibility of a game (public, publiclocked, private)"""
    chan = owned_game_channel(ctx, chan)
    game = channel_games[chan.id]
    if visibility is not None:
        game.visibility = visibility
        # overwrites = {
        #     ctx.guild.default_role: discord.PermissionOverwrite(read_messages=True)}
        for target in chan.overwrites:
            await chan.set_permissions(target, overwrite=None)
        if visibility == Visibility.Private:
            # overwrites[ctx.guild.default_role] = discord.PermissionOverwrite(
            #     read_messages=False)
            await chan.set_permissions(ctx.guild.default_role, read_messages=False)
            # overwrites[ctx.guild.me] = discord.PermissionOverwrite(
            #     read_messages=True)
            await chan.set_permissions(ctx.guild.me, read_messages=False)
            for player in game.players:
                await chan.set_permissions(player, read_messages=True)

        # await chan.edit(overwrites=overwrites)
        await ctx.send('VISIBILITY UPDATED')
    else:
        await ctx.send(f'VISIBILITY STATUS IS {Visibility.str(game.visibility).upper()}')


@guild_only()
@config.command()
async def gamemode(ctx, gamemode: typing.Optional[GameMode], chan: typing.Optional[discord.TextChannel]):
    """Set gamemode of game (anarchy or ordered)"""
    chan = owned_game_channel(ctx, chan)
    game = channel_games[chan.id]
    if gamemode is not None:
        game.gamemode = gamemode
        await ctx.send('GAMEMODE UPDATED')
    else:
        await ctx.send(f'GAMEMODE IS {GameMode.str(game.gamemode).upper()}')


@guild_only()
@config.command()
async def prompt(ctx, *, prompt: str):
    """Set the prompt of the story"""
    chan = owned_game_channel(ctx, ctx.channel)
    game = channel_games[chan.id]
    game.prompt = prompt
    await ctx.send('PROMPT SET')


@guild_only()
@config.command()
async def timeout(ctx, timeout: typing.Optional[float], chan: typing.Optional[discord.TextChannel]):
    """Set the timeout of the bot's writing"""
    chan = owned_game_channel(ctx, chan)
    game = channel_games[chan.id]
    if timeout is not None:
        game.timeout = timeout
        await ctx.send('TIMEOUT UPDATED')
    else:
        await ctx.send(f'TIMEOUT IS {game.timeout}s')


@config.group()
async def votable(ctx):
    """Configure what parts of the game are subject to democratic decision"""
    if ctx.invoked_subcommand is None:
        raise CommandNotFound()


@guild_only()
@votable.command()
async def kick(ctx, votable: typing.Optional[bool], chan: typing.Optional[discord.TextChannel]):
    """Set if players can vote to kick others"""
    chan = owned_game_channel(ctx, chan)
    game = channel_games[chan.id]
    if votable is not None:
        game.vote_kick = votable
        await ctx.send('VOTE KICK STATUS UPDATED')
    else:
        await ctx.send(f'VOTE KICK STATUS IS {str(game.vote_kick).upper()}')


@guild_only()
@votable.command()
async def revert(ctx, votable: typing.Optional[bool], chan: typing.Optional[discord.TextChannel]):
    """Set if players can vote to revert an action"""
    chan = owned_game_channel(ctx, chan)
    game = channel_games[chan.id]
    if votable is not None:
        game.vote_revert = votable
        await ctx.send('VOTE REVERT STATUS UPDATED')
    else:
        await ctx.send(f'VOTE REVERT STATUS IS {str(game.vote_revert).upper()}')


@guild_only()
@votable.command()
async def retry(ctx, votable: typing.Optional[bool], chan: typing.Optional[discord.TextChannel]):
    """Set if players can vote to retry an action"""
    chan = owned_game_channel(ctx, chan)
    game = channel_games[chan.id]
    if votable is not None:
        game.vote_retry = votable
        await ctx.send('VOTE RETRY STATUS UPDATED')
    else:
        await ctx.send(f'VOTE RETRY STATUS IS {str(game.vote_retry).upper()}')


@bot.group()
async def cmd(ctx):
    """Run or vote for commands in game"""
    if ctx.invoked_subcommand is None:
        raise CommandNotFound()


@guild_only()
@cmd.command()
async def revert(ctx):
    """Revert an action in game"""
    chan = owned_game_channel(ctx, ctx.channel)
    game = channel_games[chan.id]
    if game.calculating:
        await ctx.send('PROCESSING IN PROGRESS, PLEASE WAIT BEFORE MODIFYING STORY')
        return
    if not game.started:
        await ctx.send('GAME HAS NOT STARTED. CANNOT REVERT')
        return
    if len(game.story_manager.story.actions) != 0:
        game.story_manager.story.actions.pop()
        game.story_manager.story.results.pop()
        await ctx.send('ACTION REVERTED')
    else:
        await ctx.send('CANNOT REVERT')


@guild_only()
@cmd.command()
async def kick(ctx, player: discord.Member):
    """Kick a player from your game"""
    chan = owned_game_channel(ctx, ctx.channel)
    game = channel_games[chan.id]
    game.players.remove(player.id)
    game.player_idx %= len(game.players)
    await chan.set_permissions(player, overwrite=None)
    await ctx.send('PLAYER REMOVED')


@guild_only()
@bot.command()
async def clear_lobbies(ctx):
    """Delete all lobby channels"""
    if ctx.message.author.guild_permissions.administrator:
        for chan in get_game_channels(ctx.guild):
            await chan.delete()
        await ctx.send('64K RAM SYSTEM   38911 BASIC BYTES FREE\n\nREADY.')


@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}')


@bot.event
async def on_message(msg):
    ctx = await bot.get_context(msg)
    if ctx.valid:
        await bot.invoke(ctx)
    elif not msg.content.startswith('(') and msg.author.id != bot.user.id and ctx.guild and ctx.channel.id in channel_games:
        game = channel_games[ctx.channel.id]
        if game.started and msg.author.id in game.players:
            async with ctx.channel.typing():
                await game.add_to_queue(msg.author, msg.content)


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, CommandNotFound):
        return await ctx.send('COMMAND NOT ACCEPTED')
    return await ctx.send(f'ERROR EXECUTING COMMAND: {error}')
    # raise error

with open('.key', 'r', encoding='utf-8') as f:
    bot.run(f.read())
