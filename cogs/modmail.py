

import datetime
from typing import Optional, Union
import re 

import discord
from discord.ext import commands
import dateutil.parser

from core.decorators import trigger_typing
from core.paginator import PaginatorSession
from core.time import UserFriendlyTime, human_timedelta


class Modmail:
    """Commands directly related to Modmail functionality."""

    def __init__(self, bot):
        self.bot = bot
    
    def obj(arg):
        return discord.Object(int(arg))

    @commands.command()
    @trigger_typing
    @commands.has_permissions(administrator=True)
    async def setup(self, ctx):
        """Sets up a server for modmail"""
        if self.bot.main_category:
            return await ctx.send(f'{self.bot.modmail_guild} is already set up.')

        categ = await self.bot.modmail_guild.create_category(
            name='Mod Mail',
            overwrites=self.bot.overwrites(ctx)
        )

        await categ.edit(position=0)

        c = await self.bot.modmail_guild.create_text_channel(name='bot-logs', category=categ)
        await c.edit(topic='You can delete this channel if you set up your own log channel.')
        await c.send('Use the `config set log_channel_id` command to set up a custom log channel.')

        await ctx.send('Successfully set up server.')

    @commands.group(name='snippets')
    @commands.has_permissions(manage_messages=True)
    async def snippets(self, ctx):
        """Returns a list of snippets that are currently set."""
        if ctx.invoked_subcommand is not None:
            return

        embeds = []

        em = discord.Embed(color=discord.Color.green())
        em.set_author(name='Snippets', icon_url=ctx.guild.icon_url)

        embeds.append(em)

        em.description = 'Here is a list of snippets that are currently configured.'

        if not self.bot.snippets:
            em.color = discord.Color.red()
            em.description = f'You dont have any snippets at the moment.'
            em.set_footer(text=f'Do {self.bot.prefix}help snippets for more commands.')

        for name, value in self.bot.snippets.items():
            if len(em.fields) == 5:
                em = discord.Embed(color=discord.Color.green(), description=em.description)
                em.set_author(name='Snippets', icon_url=ctx.guild.icon_url)
                embeds.append(em)
            em.add_field(name=name, value=value, inline=False)

        session = PaginatorSession(ctx, *embeds)
        await session.run()

    @snippets.command(name='add')
    async def _add(self, ctx, name: str.lower, *, value):
        """Add a snippet to the bot config."""
        if 'snippets' not in self.bot.config.cache:
            self.bot.config['snippets'] = {}

        self.bot.config.snippets[name] = value
        await self.bot.config.update()

        em = discord.Embed(
            title='Added snippet',
            color=discord.Color.green(),
            description=f'`{name}` points to: {value}'
        )

        await ctx.send(embed=em)

    @snippets.command(name='del')
    async def __del(self, ctx, *, name: str.lower):
        """Removes a snippet from bot config."""

        em = discord.Embed(
            title='Removed snippet',
            color=discord.Color.green(),
            description=f'`{name}` no longer exists.'
        )

        if not self.bot.config.snippets.get(name):
            em.title = 'Error'
            em.color = discord.Color.red()
            em.description = f'Snippet `{name}` does not exist.'
        else:
            del self.bot.config['snippets'][name]
            await self.bot.config.update()

        await ctx.send(embed=em)

    @commands.command()
    @commands.has_permissions(manage_channels=True)
    async def move(self, ctx, *, category: discord.CategoryChannel):
        """Moves a thread to a specified cateogry."""
        thread = await self.bot.threads.find(channel=ctx.channel)
        if not thread:
            return await ctx.send('This is not a modmail thread.')

        await thread.channel.edit(category=category)
        await ctx.message.add_reaction('✅')

    async def send_scheduled_close_message(self, ctx, after, silent=False):
        human_delta = human_timedelta(after.dt)
        
        silent = '*silently* ' if silent else ''

        em = discord.Embed(
            title='Scheduled close',
            description=f'This thread will close {silent}in {human_delta}.',
            color=discord.Color.red()
            )

        if after.arg and not silent:
            em.add_field(name='Message', value=after.arg)
        
        em.set_footer(text='Closing will be cancelled if a thread message is sent.')
        em.timestamp = after.dt
            
        await ctx.send(embed=em)

    @commands.command(name='close', usage='[after] [close message]')
    async def _close(self, ctx, *, after: UserFriendlyTime=None):
        """Close the current thread.
        
        Close after a period of time:
        - `close in 5 hours`
        - `close 2m30s`
        
        Custom close messages:
        - `close 2 hours The issue has been resolved.`
        - `close We will contact you once we find out more.`

        Silently close a thread (no message)
        - `close silently`
        - `close in 10m silently`
        """

        thread = await self.bot.threads.find(channel=ctx.channel)
        if not thread:
            return
        
        now = datetime.datetime.utcnow()

        close_after = (after.dt - now).total_seconds() if after else 0
        message = after.arg if after else None
        silent = str(message).lower() in {'silent', 'silently'}

        if after and after.dt > now:
            await self.send_scheduled_close_message(ctx, after, silent)

        await thread.close(
            closer=ctx.author, 
            after=close_after,
            message=message, 
            silent=silent,
            )

    @commands.command()
    async def nsfw(self, ctx):
        """Flags a modmail thread as nsfw."""
        thread = await self.bot.threads.find(channel=ctx.channel)
        if thread is None:
            return
        await ctx.channel.edit(nsfw=True)
        await ctx.message.add_reaction('✅')

    @commands.command()
    @commands.has_permissions(manage_messages=True)
    @trigger_typing
    async def logs(self, ctx, *, member: Union[discord.Member, discord.User, obj]=None):
        """Shows a list of previous modmail thread logs of a member."""

        if not member:
            thread = await self.bot.threads.find(channel=ctx.channel)
            if not thread:
                raise commands.UserInputError

        user = member or thread.recipient

        icon_url = getattr(user, 'avatar_url', 'https://cdn.discordapp.com/embed/avatars/0.png')

        logs = await self.bot.modmail_api.get_user_logs(user.id)

        if not any(not e['open'] for e in logs):
            return await ctx.send('This user has no previous logs.')

        em = discord.Embed(color=discord.Color.green())
        em.set_author(name='Previous Logs', icon_url=icon_url)

        embeds = [em]

        current_day = dateutil.parser.parse(logs[0]['created_at']).strftime(r'%d %b %Y')

        fmt = ''

        closed_logs = [l for l in logs if not l['open']]

        for index, entry in enumerate(closed_logs):
            if len(embeds[-1].fields) == 3:
                em = discord.Embed(color=discord.Color.green())
                em.set_author(name='Previous Logs', icon_url=icon_url)
                embeds.append(em)

            date = dateutil.parser.parse(entry['created_at'])

            new_day = date.strftime(r'%d %b %Y')
            time = date.strftime(r'%H:%M')

            key = entry['key']
            user_id = entry['user_id']
            log_url = f"https://logs.modmail.tk/{user_id}/{key}"

            truncate = lambda c: c[:47] + '...' if len(c) > 50 else c

            if entry['messages']:
                short_desc = truncate(entry['messages'][0]['content']) or 'No content'
            else:
                short_desc = 'No content'

            fmt += f"[`[{time}]{key}`]({log_url}) - {short_desc}\n"

            print(fmt)

            if current_day != new_day or index == len(closed_logs) - 1:
                embeds[-1].add_field(name=current_day, value=fmt, inline=False)
                current_day = new_day
                fmt = ''

        session = PaginatorSession(ctx, *embeds)
        await session.run()

    @commands.command()
    @trigger_typing
    async def reply(self, ctx, *, msg=''):
        """Reply to users using this command.

        Supports attachments and images as well as automatically embedding image_urls.
        """
        ctx.message.content = msg
        thread = await self.bot.threads.find(channel=ctx.channel)
        if thread:
            await thread.reply(ctx.message)

    @commands.command()
    async def edit(self, ctx, message_id: Optional[int]=None, *, new_message):
        """Edit a message that was sent using the reply command.

        If no message_id is provided, that last message sent by a mod will be edited.

        `[message_id]` the id of the message that you want to edit.
        `<new_message>` is the new message that will be edited in.
        """
        thread = await self.bot.threads.find(channel=ctx.channel)

        if thread is None:
            return

        linked_message_id = None

        async for msg in ctx.channel.history():
            if message_id is None and msg.embeds:
                em = msg.embeds[0]
                if 'Moderator' not in str(em.footer.text):
                    continue
                linked_message_id = str(em.author.url).split('/')[-1]
                break
            elif message_id and msg.id == message_id:
                url = msg.embeds[0].author.url
                linked_message_id = str(url).split('/')[-1]
                break

        if not linked_message_id:
            raise commands.UserInputError

        await thread.edit_message(linked_message_id, new_message)
        await ctx.message.add_reaction('✅')

    @commands.command()
    @trigger_typing
    @commands.has_permissions(manage_channels=True)
    async def contact(self, ctx, *, user: Union[discord.Member, discord.User]):
        """Create a thread with a specified member."""

        exists = await self.bot.threads.find(recipient=user)
        if exists:
            return await ctx.send('Thread already exists.')
        else:
            thread = await self.bot.threads.create(user, creator=ctx.author)

        em = discord.Embed(
            title='Created thread',
            description=f'Thread started in {thread.channel.mention} for {user.mention}',
            color=discord.Color.green()
        )

        await ctx.send(embed=em)

    @commands.command()
    @trigger_typing
    @commands.has_permissions(manage_channels=True)
    async def blocked(self, ctx):
        """Returns a list of blocked users"""
        em = discord.Embed(title='Blocked Users', color=discord.Color.green(), description='')

        users = []
        not_reachable = []

        for id, reason in self.bot.blocked_users.items():
            user = self.bot.get_user(int(id))
            if user:
                users.append((user, reason))
            else:
                not_reachable.append((id, reason))

        em.description = 'Here is a list of blocked users.'

        if users:
            em.add_field(name='Currently Known', value='\n'.join(u.mention + (f' - `{r}`' if r else '') for u, r in users))
        if not_reachable:
            em.add_field(name='Unknown', value='\n'.join(f'`{i}`' + (f' - `{r}`' if r else '') for i, r in not_reachable), inline=False)

        if not users and not not_reachable:
            em.description = 'Currently there are no blocked users'

        await ctx.send(embed=em)

    @commands.command()
    @trigger_typing
    @commands.has_permissions(manage_channels=True)
    async def block(self, ctx, user: Union[discord.Member, discord.User, obj]=None, *, reason=None):
        """Block a user from using modmail."""

        if user is None:
            thread = await self.bot.threads.find(channel=ctx.channel)
            if thread:
                user = thread.recipient
            else:
                raise commands.UserInputError

        
        mention = user.mention if hasattr(user, 'mention') else f'`{user.id}`'

        em = discord.Embed()
        em.color = discord.Color.green()

        if str(user.id) not in self.bot.blocked_users:
            self.bot.config.blocked[str(user.id)] = reason
            await self.bot.config.update()

            em.title = 'Success'
            em.description = f'{mention} is now blocked ' + (f'for `{reason}`' if reason else '')

            await ctx.send(embed=em)
        else:
            em.title = 'Error'
            em.description = f'{mention} is already blocked'
            em.color = discord.Color.red()

            await ctx.send(embed=em)

    @commands.command()
    @trigger_typing
    @commands.has_permissions(manage_channels=True)
    async def unblock(self, ctx, *, user: Union[discord.Member, discord.User, obj]=None):
        """Unblocks a user from using modmail."""

        if user is None:
            thread = await self.bot.threads.find(channel=ctx.channel)
            if thread:
                user = thread.recipient
            else:
                raise commands.UserInputError

        mention = user.mention if hasattr(user, 'mention') else f'`{user.id}`'

        em = discord.Embed()
        em.color = discord.Color.green()

        if str(user.id) in self.bot.blocked_users:
            del self.bot.config.blocked[str(user.id)]
            await self.bot.config.update()

            em.title = 'Success'
            em.description = f'{mention} is no longer blocked'

            await ctx.send(embed=em)
        else:
            em.title = 'Error'
            em.description = f'{mention} is not blocked'
            em.color = discord.Color.red()

            await ctx.send(embed=em)


def setup(bot):
    bot.add_cog(Modmail(bot))
