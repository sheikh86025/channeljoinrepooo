class RPCError(Exception): pass
class FloodWaitError(RPCError):
    def __init__(self, seconds): super().__init__(f"wait {seconds}"); self.seconds = seconds
for _n in ["UserAlreadyParticipantError","InviteRequestSentError","ChannelsTooMuchError","InviteHashExpiredError",
           "InviteHashInvalidError","InviteHashEmptyError","UsernameInvalidError","UsernameNotOccupiedError",
           "ChannelPrivateError","ChannelInvalidError","UserBannedInChannelError","UsersTooMuchError",
           "ChatInvalidError","RpcCallFailError","SessionRevokedError","SessionPasswordNeededError",
           "PhoneCodeInvalidError","PhoneCodeExpiredError","PasswordHashInvalidError","PhoneNumberInvalidError","AccessTokenInvalidError"]:
    globals()[_n] = type(_n, (RPCError,), {})
