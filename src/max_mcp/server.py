from mcp.server.fastmcp import FastMCP

from .client import lifespan
from .tools import channels, chats, contacts, links, messages, send

INSTRUCTIONS = (
    "MAX messenger user-session tools. Use list_chats/get_chat to discover chats. "
    "read_messages/list_channel_posts to fetch history. search_messages does "
    "client-side scan (slow). dump_channel for full archive (cap 1000 posts per "
    "call). send_message/send_file for writes. Contacts: find_user_by_phone / "
    "get_user resolve people; add_contact/remove_contact/list_contacts/"
    "import_contacts manage the phone book; send_message_by_phone DMs someone by "
    "number in one call (get_dialog_chat_id gives the 1:1 chat_id from a user id). "
    "Public links: resolve_link turns a max.ru/u/<token> or max.ru/id..._biz link "
    "into a chat_id/user_id; send_message_by_link resolves and DMs in one call."
)

mcp = FastMCP("max-mcp", instructions=INSTRUCTIONS, lifespan=lifespan)
chats.register(mcp)
messages.register(mcp)
channels.register(mcp)
send.register(mcp)
contacts.register(mcp)
links.register(mcp)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
