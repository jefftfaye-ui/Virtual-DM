"""One-time script: load Session 1 history into the messages table.
Run: PYTHONPATH=. python scripts/load_session1.py
"""
import asyncio, os
from dotenv import load_dotenv
load_dotenv()
from db import repo

CAMPAIGN_ID = 'e0a6e6bd-9b9e-4a42-af3b-401d6a6dd4ff'

MESSAGES = [
('assistant', None, """Session 1 is live — welcome, Jeff and Julee.

Before I set the opening scene, I need a little from you both, because the campaign slate is completely blank right now: no characters imported, no established location, no quests in motion.

Out of character, quick setup:

Characters — Do you want to import from D&D Beyond (share the public character URLs), or should we build/stat them another way?
Tone & setting — Any preferences? Classic sword-and-sorcery, grim low-magic, high-fantasy weird, something else?
Starting hook — Prefer the ol' "you meet in a tavern," waking up somewhere strange with no memory, hired for a specific job, or shall I surprise you?

Once I know who you're playing and roughly where you want to begin, I'll drop you into a scene that actually matters — with something in front of you that demands a choice on turn one."""),

('user', 'Jeff', 'https://www.dndbeyond.com/characters/172244124/S5z12l'),

('assistant', None, """On it — importing Jeff's character now.

Specter Keihl Deux (Warlock 3) is loaded, Jeff. One thing — AC didn't auto-derive. What's your AC? Drop that in and we're set on your end.

Julee — are you importing a character too, or sitting this one out? If you're playing, drop your D&D Beyond URL (or let me know how you want to build).

While we wait, give me a couple quick choices to anchor the opening:

Specter's vibe — Any hooks you want me to lean into? Patron, pact, backstory beats, place of origin?
Starting locale — frontier town, crumbling imperial capital, haunted coastline, something colder?

Give me AC, Julee's status, and even a sentence of flavor, and I'll open the scene properly."""),

('user', 'Jeff', "Def a forged noble with a heck of an eldritch blast. He's tricky, clever and has high riz"),

('assistant', None, """Got it — forged noble, silver tongue, eldritch blast like a thunderclap. I'll weave that in.

Still need two things before I open the scene:

Specter's AC (D&D Beyond didn't push it through)
Julee — are you playing tonight? If so, drop a character URL or let me know how you want to proceed.

Give me those and I'll drop the curtain."""),

('user', 'Jeff', 'AC - 15 - Julee is playing, just getting her new character ready'),

('assistant', None, """AC 15 locked in. Specter is ready to roll.

Standing by for Julee's character — drop the URL (or sheet details) whenever she's ready, and I'll open the scene the moment she's at the table."""),

('user', 'Julee', 'https://www.dndbeyond.com/characters/164439701/s2IXvv'),

('assistant', None, """Emodie is loaded, Julee — welcome.

Same hiccup as Jeff: AC didn't auto-derive. What's Emodie's AC? Drop that and give me a sentence of vibe/class if you want me to weave her in with any particular flavor.

Once I have AC, I open the scene."""),

('user', 'Julee', '12'),

('assistant', None, """Both characters locked. Let me set the stage.

Rain drums on the slate roof of the Gilded Vane. Inside, the common room is warm and crowded — teamsters playing bones by the fire, a bard tuning a battered lute she clearly has no intention of actually playing, a serving girl threading between benches with a tray of pewter mugs. Onion stew. Wet wool. Pipe smoke curling blue beneath the rafters.

You two have the corner table, backs to the stone — Specter's choice, probably. The hearth throws good heat on your left side. Half-eaten bowls between you. Outside, the storm has turned the Marchroad to a black river of mud, which means nobody's leaving tonight.

The innkeeper — a thick-wristed man named Harl — just climbed the back stairs with a taper to light the second-floor lanterns. His bootsteps thump overhead.

Three tables over, there's a party of travelers in oilcloth cloaks. They came in before you did, took their meal in near silence, and have been nursing the same tankards for an hour. Two of them keep their hoods up indoors — which is rude, in these parts.

The third just pulled his hood back. Shaved scalp. A pale knotwork tattoo climbing out of his collar and up the side of his neck. He is looking directly at Specter. Not glancing. Looking. Has been, you now realize, for probably half a minute.

Emodie — the hearth beside you pops, and a cinder jumps the grate. In the sudden flare of light, you catch something: the tattooed man's two companions aren't drinking. Their mugs are full. And the one on the left has a hand under the table.

What do you do?"""),

('user', 'Julee', 'Update the AC to 17 and HP to 25'),

('assistant', None, """Updated. Emodie now AC 17, HP 25/25.

Back to the Gilded Vane — tattooed man staring at Specter, his companion's hand under the table, the hearth crackling. What do you two do?"""),

('user', 'Jeff', 'can you read aloud?'),

('assistant', None, """Reading what aloud, Jeff? Want to clarify —

A sign, a menu, a document in the inn you're examining?
The scene recap — want me to re-read the setup?
Specter reading the tattooed man — like, reading his intent/body language? (That'd be an Insight check.)

Point me and I'll run it."""),

('user', 'Jeff', 'The staging'),

('assistant', None, """You got it. Here it is again:

Rain drums on the slate roof of the Gilded Vane. Inside, the common room is warm and crowded — teamsters playing bones by the fire, a bard tuning a battered lute she clearly has no intention of actually playing, a serving girl threading between benches with a tray of pewter mugs. Onion stew. Wet wool. Pipe smoke curling blue beneath the rafters.

You two have the corner table, backs to the stone — Specter's choice, probably. The hearth throws good heat on your left side. Half-eaten bowls between you. Outside, the storm has turned the Marchroad to a black river of mud, which means nobody's leaving tonight.

The innkeeper — a thick-wristed man named Harl — just climbed the back stairs with a taper to light the second-floor lanterns. His bootsteps thump overhead.

Three tables over, there's a party of travelers in oilcloth cloaks. They came in before you did, took their meal in near silence, and have been nursing the same tankards for an hour. Two of them keep their hoods up indoors — which is rude, in these parts.

The third just pulled his hood back. Shaved scalp. A pale knotwork tattoo climbing out of his collar and up the side of his neck. He is looking directly at Specter. Not glancing. Looking. Has been, you now realize, for probably half a minute.

Emodie — the hearth beside you pops, and a cinder jumps the grate. In the sudden flare of light, you catch something: the tattooed man's two companions aren't drinking. Their mugs are full. And the one on the left has a hand under the table.

What do you two do?"""),

('user', 'Julee', "I'm going to roll investigation check and see what is under the table"),

('assistant', None, """Good instinct — but from across the room, through a crowded common room, with his hand already hidden? That's not something you can just see. You'd need to get closer, create a distraction, or angle for a better line of sight.

A couple options:

Perception (passive observation from here) — can you catch any other tells?
Insight — read the group's body language. Are they about to move? Nervous? Confident?
Get up and move — go to the bar, pass their table, "trip" — now you've got a real angle.

Which flavor do you want?"""),

('user', 'Julee', 'roll insight'),

('assistant', None, "Roll it — d20 + Emodie's Insight modifier. Tell me the total (and the natural if it's a 1 or 20)."),

('user', 'Julee', '20'),

('assistant', None, """Let me log that.

You let your eyes unfocus the way you do — not staring, just seeing — and the whole little tableau opens up like a cut flower.

The tattooed man isn't a thug. His posture is too settled. Shoulders square, weight centered, hands relaxed on the table — the ease of someone who has done violence before and expects to do it again, and doesn't need to posture about it. He's the one in charge.

The two hooded ones are his. The one on the right is young — you can tell by the knuckles on the tankard, pink and unscarred. He's scared. Not scared of you — scared of messing up in front of the boss.

The one on the left, the hand-under-the-table one — he's not holding a weapon. His wrist angle is wrong for a blade or crossbow. He's holding something small, and his thumb is moving in a slow, deliberate circle. A focus. A token. Possibly a holy symbol. Possibly a spell component.

And the big read, the one the 20 earns you:

They're not here to rob anyone. They're here for someone. The tattooed man's gaze keeps returning to Specter — but it's not hungry or hateful. It's the look of a man confirming an identification. He's checking Specter against a description he was given.

They've been waiting for him.

Specter — Emodie's foot finds your ankle under the table. A single tap. Trouble. Yours."""),

('user', 'Jeff', "Can I cast unseen servant and nod emodie to walk there way?"),

('assistant', None, """Oh, that's clever.

Quick rules check: Unseen Servant is a 1st-level ritual — 1 minute to cast as a ritual (no slot), or 1 action if you burn a slot.

Ritual (1 minute) — Verbal + Somatic components. You'd be murmuring and gesturing for a full minute while under direct observation. Doable if you cover it.
Spell slot (1 action) — Fast, but very obviously a spell to anyone watching.

The servant can manipulate objects, open doors, fetch things, pour drinks. It cannot attack. But it could nudge a tankard, tip a candle, open a door, lift the hem of a cloak...

Tell me: Ritual or slot? How are you covering it? What do you want the servant to do once it's up?

Julee — are you nodding and walking over? If yes, with what pretext?"""),

('user', 'Jeff', "I'll roll slight of hand, disguse the ritual as a prayer."),

('assistant', None, """Perfect — exactly the kind of thing a forged noble with riz would do. Bow the head, murmur over the stew, trace a slow sigil above the bowl like you're blessing the meal.

Roll Sleight of Hand (or Deception — your call, whichever is higher). Give me the d20 + modifier.

Julee — are you moving? The ritual takes a full minute; cover from Emodie would help."""),

('user', 'Julee', "I'll get up as he 'prays' and walk as if to the privy to allow the group to walk over and attack from behind if needed"),

('assistant', None, """Perfect. Specter bows his head and begins the low murmur, fingers tracing a slow spiral above his bowl — the picture of a devout man at grace. Emodie slides off the bench, stretches like she's been sitting too long, and starts an unhurried diagonal toward the back hall where the privy sign hangs — a route that just happens to carry her past and slightly behind the strangers' table.

Jeff — give me that Sleight of Hand (or Deception) roll.

Julee — give me a Stealth check to make the path look casual."""),

('user', 'Jeff', '24'),

('assistant', None, """Flawless. Specter's murmur has the exact right cadence — a traveler's blessing, nothing worth watching. His hand moves with the unconscious grace of someone who's done this a thousand times at ten thousand tables. The tattooed man's eyes flick to him once, dismiss the gesture, and go back to tracking the room.

A full minute passes. The air at Specter's shoulder condenses — a cool, patient presence, waiting for instruction. The Unseen Servant is up.

Now — Julee, Stealth (or Performance) for the casual walk to the privy. Give me a total."""),

('user', 'Julee', '4'),

('assistant', None, """Oof. The stretch is a half-beat too theatrical. The yawn doesn't quite land. And when you push off the bench, your hip catches the table hard enough that both bowls jump and a spoon clatters to the floor.

Every face at the strangers' table turns.

The scared young one actually flinches — hand twitching toward his belt before he catches himself. The tattooed man's gaze locks onto you and stays there. The one with his hand under the table hasn't moved his hand, but his thumb has stopped circling.

The tattooed man speaks. His voice is quiet, carrying, and almost kind.

"Easy there, friend. Long day?"

He gestures at the empty chair at their table.

"Sit. Have a drink with us. You and the man doing the praying both. We've been hoping to make his acquaintance."

The room's noise flows back in around you. The little bubble around these four tables has gone very, very attentive.

Specter — the servant hovers at your shoulder, awaiting a command. Emodie — you're standing in the open, three paces from their table, every eye on you.

What do you do?"""),

('user', 'Jeff', '"I would be happy to join you, friends! Make room, make room" Silent command to the servant is to move to their table ready to help if needed'),

('assistant', None, """Specter rises with the easy grace of someone who has crashed better parties than this one — a warm smile, both hands visible, the picture of a well-bred traveler delighted by unexpected company. The invisible servant drifts along at his shoulder like a loyal hound, silent in the rushes.

He crosses the floor, pulls out the open chair with a flourish, and settles in across from the tattooed man. Up close, you can see more of the knotwork tattoo — it climbs from collarbone to jaw in interlocking loops, and the ink isn't black. It's a very dark, very old red.

The tattooed man watches Specter sit. Then he looks past him to Emodie, still standing, and tips two fingers at the last empty chair.

"And you, dear. Please."

He waits until you're both seated, then signals the serving girl for two more mugs.

"My name is Varric Oen," he says. "These are my associates — doesn't matter which is which. We've ridden four days in weather that would drown a duck, and we did it because a man in Hallowmere told us a story about a young lord with silver in his throat and lightning in his hand, who was traveling the Marchroad in company with" — his eyes slide to Emodie — "a sharp-eyed friend."

He folds his hands. The knuckles are scarred white.

"The story he told us ended badly for the young lord. We'd very much like it to end differently. So before anyone does anything regrettable —" a glance at the hand still under the table, which withdraws and settles empty on the tabletop — "I'd like to ask you one question, and I'd like a true answer."

He leans in. The red tattoo seems to drink the firelight.

"Does the name Caedren Vosh mean anything to you?"

The serving girl arrives with the mugs. Sets them down. Leaves. Nobody touches them.

What do you do?"""),

('user', 'Jeff', 'roll a history check'),

('assistant', None, "Roll it — d20 + Specter's History modifier. Give me the total (and the natural if 1 or 20)."),

('user', 'Jeff', '11'),

('assistant', None, """Specter searches the vaults of his careful, cultivated education — the genealogies, the merchant rolls, the whispered courtly scandals a forged noble has to know cold to pass.

Caedren Vosh. The name has... weight. Not a house name you'd find on a banner. Not a merchant prince. But you've heard it — maybe twice, maybe three times, always in passing, always from someone who then changed the subject. A name people drop and then pretend they didn't.

You can't place him. Not a title, not a city, not a crime. But the shape of the silence around the name tells you something: Caedren Vosh is the kind of person other dangerous people are quietly afraid of.

That's all the 11 gives you. Varric is watching your face. He is very, very good at watching faces.

What do you say?"""),

('user', 'Jeff', '"I\'ll be honest. He is a ghost, a specter, a name that is dropped, then never spoken of again. I do not know Caedren Vosh, I only know the shape of his name\'s impact"'),

('assistant', None, """Varric Oen holds very still for a long moment. Then, slowly, the corner of his mouth lifts — not quite a smile. Something more like recognition.

"That," he says softly, "is the most honest answer I have heard in four days of asking. And the most useful."

He picks up his mug finally. Takes a slow pull. Sets it down.

"The man in Hallowmere told us you'd been asking questions about a sealed warehouse on the Cinderquay. He said you asked them politely, which is why he was willing to speak to us at all — the last three people to ask about that warehouse asked impolitely, and one of them is now in the river in several convenient pieces."

The scared young one shifts uncomfortably.

"The shape you felt around Vosh's name is correct. He is the quiet hand behind a great deal of ugly commerce on this stretch of the Marchroad, and that warehouse is one of his. My associates and I have reasons of our own to want its contents brought into the light. We lack a certain kind of asset. Specifically: someone who can walk into a room full of wolves and be mistaken for one of them."

His eyes flick over Specter's clothes. The cut. The quality. The performance.

"We can pay. Or we can trade — information for information. A name for a name. Your choice. But the window is small; Vosh moves the shipment in six days, and once it is moved, it is gone."

He leans back. Spreads his hands.

"So. I have been honest in return. What would you like to do, young lord with lightning in his hand?\"

Emodie — he hasn't addressed you directly, but his eyes have flicked to you twice while speaking. He is very aware you're part of this decision.

Both of you — what do you do?"""),

('user', 'Jeff', '"We are always happy to help a friend, and I think that you would be quiet pleased to find out my partner\'s talents. Before we inquire further, help me understand the item which you have misplaced, and what infomation may be of particular interest to us"'),

('assistant', None, """Varric's eyes crinkle at misplaced — he appreciates the word choice.

"Spoken like a man who negotiates for a living. Very well."

He glances once around the common room. Cover enough. He leans in, and his voice drops to a register that doesn't carry past the four of you.

"The warehouse holds three things. One is mundane — bolts of Khemrish silk, untaxed, worth perhaps two thousand crowns on an honest market. You are welcome to it; it is not why we are here."

One finger lifts.

"The second is a ledger. Bound in red calfskin, locked, kept in an iron strongbox bolted to the floor of the counting-room on the second level. That ledger lists every magistrate, harbor-reeve, and temple-almoner on the lower Marchroad who takes Vosh's coin. We will pay four hundred crowns for it, delivered unopened — or six hundred if you deliver it opened and can tell us it has not been copied."

A second finger.

"The third thing is why Vosh is moving the shipment at all. A child. Nine years old. Taken from a village called Penmarch three weeks ago. We want her out. Alive. Unharmed as possible. For that —" he looks directly at Specter, then at Emodie "— we will pay whatever we have, and we have more than we look like we have. And we will owe you a debt that will be honored in places you did not know we had reach."

He sits back.

"As for information you might want from us — I can tell you the warehouse's layout, the guard rotation, the name of the dockmaster who looks the other way on third-watch, and one specific weakness in the counting-room's lock that cost a man his thumbs to learn."

He finally takes the drink.

"Your turn, young lord. What are your terms?"""),

('user', 'Jeff', "Got it - girl first, book second - ignore the bolts - greed bites. There is something you are not telling us. Lay it out, and we'll continue talking. Don't and we walk."),

('assistant', None, """The scared young one draws in a sharp little breath. The spell-focus one doesn't move at all, but his eyes close for half a second. Resignation.

Varric Oen looks at Specter for a long, measuring moment. Then he laughs — just once, soft, through the nose. Like a man who's been told the price and finds it fair.

"Good. Good. I was waiting to see if you'd ask."

He sets the mug down and leaves his hands flat on the table, palms up.

"Three things I did not say.

"First. We are not thieves and we are not mercenaries. My associates and I serve an order that most people believe died out two centuries ago. The order has reasons to oppose Caedren Vosh that are older than this warehouse, older than this town, older than the current king's great-grandfather. We would prefer to keep the order's name out of this conversation, because knowing it makes you a target for the rest of your life. I will give you the name if you insist, but I would rather you did not insist until after we have shaken hands."

A beat.

"Second. The child is not an ordinary child. We do not know what she is — only that Vosh paid a sum for her acquisition that would ransom a prince, and that the man who delivered her to the warehouse walked out of it the next morning twenty years older than he walked in. Whatever she is, she is dangerous to be near, and more dangerous to leave in his hands. We would not ask you to take this on blind, so I am telling you now: getting her out may cost you more than coin."

He meets Specter's eyes directly on the third.

"Third. The reason we need you specifically — a well-dressed young lord with a silver tongue — and not a company of our own blades, is that the warehouse's front door opens tomorrow night for a buyer's viewing. Invitation only. Vosh is auctioning the girl. We have an invitation. We do not have anyone who can carry it through the door without being recognized and gutted in the entry hall. You can. Your friend here —" his eyes move to Emodie — "could pass as your retainer, your bodyguard, or your appraiser, as suits her. Once inside, you have perhaps two hours before the viewing proper begins. Everything else — the ledger, the girl, the exit — depends on what you do in those two hours."

He folds his hands again.

"That is everything I did not say. Walk if you must; I will not stop you, and I will not come looking. Stay, and we have a great deal to plan before dawn."

The rain hammers the roof. The hearth pops. Somewhere upstairs, Harl's boots are coming back down the stairs.

What do you do?"""),

('user', 'Julee', 'Alright then, Tell us the plan'),

('assistant', None, """Varric exhales — a man who has been holding a small, patient fear and now sets it down.

"Thank you."

He signals the spell-focus man, who produces from inside his cloak a tight roll of oilcloth and spreads it on the table between the mugs. It's a floor plan, inked in a careful hand — two stories, the lower marked CINDERQUAY WAREHOUSE 3, the upper marked COUNTING / HOLDING / VIEWING GALLERY.

Varric taps as he talks. His finger is steady.

"The approach. The Cinderquay is Vosh's. Don't try to come in by water; the harbor-reeve on third-watch is in his pocket and will sound a bell if an unfamiliar hull touches the pier. You arrive by carriage, from the landward side, at the hour of the ninth bell. We provide the carriage, the driver, and the livery. The driver is one of ours and will wait the full two hours; if you are not back by the eleventh bell, he leaves, and you are on your own getting out.

"The door. Two guards. You present this —" he produces a folded square of waxed vellum sealed with a drop of green wax pressed with a crow's-foot sigil "— and give the name Lord Harran Vey of Sellowmarch. Vey is a real buyer; he is also, as of two nights ago, indisposed in a way that will keep him from attending. The seal is genuine. The name will be on the list. You —" to Specter "— are Lord Vey for the evening. Your friend is whatever you want her to be; the invitation permits one companion.

"Inside. Entry hall, cloakroom, then the great room where the other buyers will be mingling before the viewing. Expect six to ten of them, plus Vosh's people. Do not attempt the ledger during the mingling — the counting-room is on the second floor and the stair is watched. You wait for the viewing to begin. When the buyers are called upstairs to the gallery —" he taps the upper floor "— the counting-room empties, because every clerk and every guard on that level moves to manage the auction. That is your window. Perhaps twenty minutes.

"The ledger. Counting-room, iron strongbox bolted to the floor, lock of Hallish make. The specific weakness: the Hallish lock has a false third tumbler. A pick that engages the second and skips the third opens it clean. A pick that engages all three jams it permanently and rings a small bell in the dockmaster's office. Your retainer looks like she can be trusted with that information." A nod to Emodie.

"The girl. Held in the small chamber marked here —" his finger stops on a room off the gallery, labeled HOLDING "— until the viewing. During the viewing she will be brought into the gallery itself and displayed on a raised dais. Taking her from the holding room is quieter but requires passing a single interior guard. Taking her from the dais is louder but she will already be unshackled for display. Your call, in the moment.

"The exit. Back stair, through the kitchens, out the servant's door onto the alley behind the quay. The carriage will be there by then — the driver repositions at the tenth bell. If the alley is blocked, there is a coal-chute at the north wall; it is a filthy exit but it is an exit.

"If it all goes wrong. Run north, not south. South is Vosh's. North is nobody's, and nobody's is better than his."

He sits back.

"That is the plan. The carriage comes for you at dusk tomorrow. Between now and then, you rest, you drill the names, and you ask me every question you have. I would rather answer a hundred stupid ones tonight than one clever one too late."

He finally picks up his mug and drains half of it in one pull.

"So. Ask." """),

('user', 'Jeff', 'save progress here. bed time!'),

('assistant', None, """You got it. Let me save state and wrap the session cleanly.

Session 1 ends here. The plan is made. The carriage comes at dusk tomorrow. Sleep well."""),
]

async def main():
    async with repo.tx() as conn:
        await repo.execute(conn,
            'DELETE FROM messages WHERE campaign_id = %s', (CAMPAIGN_ID,))
        for role, speaker, content in MESSAGES:
            await repo.execute(conn,
                'INSERT INTO messages (campaign_id, role, speaker, content) VALUES (%s,%s,%s,%s)',
                (CAMPAIGN_ID, role, speaker, content))
        row = await repo.fetchone(conn,
            'SELECT count(*) as n FROM messages WHERE campaign_id=%s', (CAMPAIGN_ID,))
        print(f"Inserted {row['n']} messages for Golden Vault campaign.")

if __name__ == '__main__':
    asyncio.run(main())
