# you probably don't want this yet

# the eyetrackvr pipeline

It looks like you are referring to the integration between EyeTrackVR (the open-source DIY hardware/software eye-tracking ecosystem) and the Valve Steam Frame, Valve's high-end VR headset. [1, 2, 3] 
Because the Steam Frame comes equipped with dual built-in interior eye cameras but natively only tracks gaze vector/foveation, users utilize a specific setup to bridge it with software like EyeTrackVR or Baballonia to achieve full eye expressions (like tracking eye openness, squinting, and blinking) for PCVR avatars in VRChat. [3, 4, 5, 6] 
## How the Integration Works
Instead of having to build custom 3D-printed mounts and IR camera rigs (which EyeTrackVR is traditionally famous for on older headsets like the Valve Index), the Steam Frame allows you to extract its native hardware video streams. [1, 6, 7] 

   1. The Sightline Bridge: To make this work, Valve users use an official companion app on Steam called [Sightline](https://store.steampowered.com/app/5290100/). [6, 8] 
   2. Video Streaming: Sightline extracts both of the Steam Frame’s interior eye-camera video feeds and streams them locally over HTTP. [6] 
   3. EyeTrackVR Processing: The EyeTrackVR software connects directly to these network video streams. It bypasses the need for physical modifications and uses its own tracking algorithms to calculate pupil position, blink data, and eye openness. [6, 9] 
   4. VRChat Output: This tracked data is fed back into your PC VR environment (usually via VRCFaceTracking or OSC) to perfectly animate your virtual avatar. [3, 6, 10] 

## Standard Software Pipeline
If you are setting this up, your background pipeline will look like this:

[Steam Frame Eye Cameras] 
          │
          ▼
   [Sightline App] (Feeds HTTP video streams)
          │
          ▼
   [EyeTrackVR] (Processes blink & look tracking)
          │
          ▼
[googly-vr / VRCFaceTracking / OSC] ──► [VRChat / Game Avatar]

This setup does not interfere with the headset's native tracking; the Steam Frame will continue to safely run its internal foveated rendering/streaming mechanics in the background while EyeTrackVR handles the avatar expressions. [4, 6] 
Are you looking for help configuring EyeTrackVR to read the Sightline camera stream, or do you need assistance troubleshooting VRCFaceTracking/OSC mapping inside VRChat?

[1] [https://store.bigscreenvr.com](https://store.bigscreenvr.com/blogs/beyond/eye-tracking-for-bigscreen-beyond-with-eyetrackvr)
[2] [https://docs.eyetrackvr.dev](https://docs.eyetrackvr.dev/getting_started/intro)
[3] [https://www.facebook.com](https://www.facebook.com/fb-answers/steam-frame-vrchat-eye-tracking/)
[4] [https://steamcommunity.com](https://steamcommunity.com/app/250820/discussions/0/688615158419892143/)
[5] [https://www.ign.com](https://www.ign.com/articles/steam-frame-preview-hands-on-with-valves-state-of-the-art-vr-headset)
[6] [https://store.steampowered.com](https://store.steampowered.com/app/5290100/Sightline/?snr=1_300_morelikev2__105_5)
[7] [https://www.reddit.com](https://www.reddit.com/r/ValveIndex/comments/1ihdaxy/index_eyetrackvr_build_tutorial/)
[8] [https://store.steampowered.com](https://store.steampowered.com/app/5290100/)
[9] [https://www.youtube.com](https://www.youtube.com/watch?v=SumuUznu8xc&t=1)
[10] [https://store.bigscreenvr.com](https://store.bigscreenvr.com/blogs/beyond/beyond-2e-eyetracking-setup-guide-with-vrchat)


https://store.steampowered.com/app/5290100/Sightline/

## how to simulate eyetrackvr output

Yes, you can easily develop an app that expects EyeTrackVR data without having any physical tracking hardware or a VR headset. Because EyeTrackVR relies on open, standardized networking protocols, you have a couple of great options to fake or simulate the data: [1] 
## Option 1: Use an OSC/UDP Dummy Data Broadcaster (Recommended)
EyeTrackVR transmits all of its processed tracking variables (like pupil coordinates, blink states, and openness values) using OSC (Open Sound Control) over standard UDP loopback (127.0.0.1). [1, 2] 
Since it uses this open protocol, you don't even need the EyeTrackVR desktop client running to develop your app. You can write a tiny helper script to act as your simulator:

* 
* The Concept: Write a basic script (in Python, Node.js, C#, etc.) that generates dummy tracking numbers—such as a sine wave pattern for looking around, or periodic zeroes to simulate a blink.
* The Implementation: Direct that script to broadcast those values over the default EyeTrackVR OSC port (usually port 9000). Your primary app will receive these packets exactly as if they were coming from real hardware. [2] 
* 

## Option 2: The EyeTrackVR Software Video Loopback
If you are specifically building or debugging an app that integrates directly into EyeTrackVR's Python/OpenCV back-end algorithms, the desktop app allows you to swap physical hardware for a local video file or a virtual webcam feed:

* 
* You can save an MP4 video clip of an actual eye blinking and looking around.
* In the EyeTrackVR software interface, select a video file or OBS Virtual Camera as the camera input source instead of choosing a hardware IP/USB camera. [3, 4] 
* The software will process that video loop in real-time, giving you a predictable, repeatable baseline data feed to test your app's responses. [4, 5] 
* 

## Quick Reference: The Data Structure You Are Faking
If you take the first route (broadcasting raw OSC), your app should listen for standard EyeTrackVR avatar addresses. The most common data points sent over OSC look like this:

* 
* /avatar/parameters/LeftEyeX and RightEyeX (Float between -1.0 and 1.0)
* /avatar/parameters/LeftEyeY and RightEyeY (Float between -1.0 and 1.0)
* /avatar/parameters/LeftEyeLidExpanded and RightEyeLidExpanded (Float between 0.0 for closed and 1.0 for wide open) [6] 
* 

What language or game engine (e.g., Unity, Unreal, Python, C++) are you writing your app in? I can provide a quick, drop-in snippet to mock the data for your setup.

[1] [https://docs.eyetrackvr.dev](https://docs.eyetrackvr.dev/getting_started/intro)
[2] [https://github.com](https://github.com/EyeTrackVR/EyeTrackVR)
[3] [https://www.youtube.com](https://www.youtube.com/watch?v=h2hPR8Mx6Ho)
[4] [https://www.youtube.com](https://www.youtube.com/watch?v=hWjLPhBlTtQ)
[5] [https://www.youtube.com](https://www.youtube.com/watch?v=l95eJe8MV5g&t=38)
[6] [https://github.com](https://github.com/EyeTrackVR/ETVRTrackingModule/activity?sort=ASC)

# details on osc protocol

The OSC (Open Sound Control) protocol is the standard protocol for eye tracking, face tracking, and full-body tracking in the social VR ecosystem. [1, 2] 
Despite its audio-centric name, OSC is essentially a lightweight, uncompressed data format wrapped inside standard UDP network packets. Because it is fast and simple, apps like EyeTrackVR Docs use it to transmit real-time eye data directly across your local machine (127.0.0.1). [1, 2, 3] 
An OSC packet is human-readable and structured exactly like a website URL pattern followed by a data type. It contains three elements:

   1. The Address String: A path prefix that routes the data (e.g., /avatar/parameters/LeftEyeX).
   2. The Type Tag: A marker indicating the data type (e.g., ,f for float, ,i for integer, ,b for boolean).
   3. The Payload: The actual raw binary tracking data (e.g., 0.523). [2, 4, 5, 6] 

When developing your application, you will notice that programs handle eye tracking through two distinct OSC philosophies: [2, 7] 

| Metric / Feature | Native VRChat Tracking Routing | VRCFaceTracking (VRCFT) Parameter Routing |
|---|---|---|
| Address Pattern | /tracking/eye/... | /avatar/parameters/... |
| Gaze Handling | Expects mathematical Pitch/Yaw degree or Vector fields. | Expects simple, normalized linear 2D bounding boxes (-1.0 to 1.0). |
| Eye Separation | Blinking uses a unified mathematical EyesClosedAmount. | Independent left and right eye tracking (LeftEyeLid, RightEyeLid). |
| Use Case | Quick plug-and-play math engine built straight into a runtime game engine. | Rich expressions like squints, pupillometry, and custom cartoon styling. |

If you are coding a program to listen to or mimic this data stream, the most important parameters to map are based on the industry-standard [VRCFaceTracking Unified Expressions](https://docs.vrcft.io/docs/v4.0/tutorial-avatars/tutorial-avatars-extras/parameters/eye-tracking-parameters) format: [5] 

* 
* Look Horizontal: /avatar/parameters/LeftEyeX & RightEyeX (Float -1.0 is looking left, 1.0 is looking right)
* Look Vertical: /avatar/parameters/LeftEyeY & RightEyeY (Float -1.0 is looking down, 1.0 is looking up)
* Eyelid Openness: /avatar/parameters/LeftEyeLidExpanded & RightEyeLidExpanded (Float 0.0 is tightly shut/squeezing, 0.8 is standard relaxed open, and 1.0 is wide-eyed surprise)
* Pupil Size: /avatar/parameters/EyesPupilDiameter (Float scaling from 0.0 to 1.0 representing millimeter diameter expansions) [5] 
* 

By default, the eye-tracking loop functions on a local client handshake:

* 
* Port 9000 (UDP Input): The destination where a game engine or client listens for external trackers to send their packets.
* Port 9001 (UDP Output): The port where the app broadcasts out parameters whenever state updates happen internally. [2] 
* 

Because it is stateless over UDP, you do not have to handle connection states, reconnect dropouts, or TCP overhead packets. You simply open up a UDP socket, listen for strings starting with the parameters above, and extract the floats directly into your game loop. [4] 

[1] [https://huyang.life](https://huyang.life/Projects/EyeTrackVR/EyeTrackVR.html)
[2] [https://www.tripo3d.ai](https://www.tripo3d.ai/blog/free-face-tracking-vrchat)
[3] [https://docs.eyetrackvr.dev](https://docs.eyetrackvr.dev/getting_started/intro)
[4] [https://docs.vrchat.com](https://docs.vrchat.com/docs/osc-avatar-parameters)
[5] [https://docs.vrcft.io](https://docs.vrcft.io/docs/v4.0/tutorial-avatars/tutorial-avatars-extras/parameters/eye-tracking-parameters)
[6] [https://docs.vrchat.com](https://docs.vrchat.com/docs/osc-eye-tracking)
[7] [https://www.tripo3d.ai](https://www.tripo3d.ai/blog/vrchat-avian-avatar-eye-tracking)
