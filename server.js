import express from "express";
import cors from "cors";
import dotenv from "dotenv";
import { SkyWayAuthToken, nowInSec, uuidV4 } from "@skyway-sdk/token";

dotenv.config();

const app = express();
app.use(cors());
app.use(express.json());

const appId = process.env.SKYWAY_APP_ID;
const secret = process.env.SKYWAY_SECRET_KEY;
const port = process.env.PORT || 3000;

if (!appId || !secret) {
  console.error("Missing SKYWAY_APP_ID or SKYWAY_SECRET_KEY");
  process.exit(1);
}

function safeRoomName(value) {
  return String(value || "main-room")
    .trim()
    .replace(/[^a-zA-Z0-9_-]/g, "")
    .slice(0, 32) || "main-room";
}

app.get("/", (_req, res) => {
  res.send("SkyWay token server is running.");
});

app.post("/api/skyway-token", (req, res) => {
  try {
    const roomName = safeRoomName(req.body?.roomName);
    const roomType = req.body?.roomType === "p2p" ? "p2p" : "sfu";

    const token = new SkyWayAuthToken({
      jti: uuidV4(),
      iat: nowInSec(),
      exp: nowInSec() + 60 * 60,
      version: 3,
      scope: {
        appId,
        rooms: [
          {
            name: roomName,
            methods: ["create", "close", "updateMetadata"],
            member: {
              name: "*",
              methods: ["publish", "subscribe", "updateMetadata"]
            },
            ...(roomType === "sfu" ? { sfu: { enabled: true } } : {})
          }
        ]
      }
    }).encode(secret);

    res.json({ token });
  } catch (error) {
    console.error(error);
    res.status(500).json({ error: "Failed to create token." });
  }
});

app.listen(port, "0.0.0.0", () => {
  console.log(`Server running on port ${port}`);
});
