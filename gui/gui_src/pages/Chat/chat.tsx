function Chat() {
  return (
    <div className="p-8">

      {/* Page Title */}
      <h1 className="mb-8 text-4xl font-bold">
        AI Chat
      </h1>

      {/* Chat Window */}
      <div className="h-[500px] rounded-2xl bg-[#111827] p-6">

        {/* AI Welcome Message */}
        <div className="mb-6">

          <div className="inline-block rounded-xl bg-cyan-700 p-4">

            🤖 Hello! I'm Piezo-LLM.

            <br />

            Ask me anything about molecular piezoelectric crystals.

          </div>

        </div>

      </div>

      {/* Chat Input */}
      <div className="mt-6 flex gap-4">

        <input
          type="text"
          placeholder="Ask about any molecular crystal..."
          className="flex-1 rounded-xl bg-[#111827] p-4 outline-none"
        />

        <button
          className="rounded-xl bg-cyan-600 px-8 py-4 hover:bg-cyan-700"
        >
          Send
        </button>

      </div>

    </div>
  );
}

export default Chat;