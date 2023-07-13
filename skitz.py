import os
import openai
from dotenv import load_dotenv
from music21 import *
from midi2audio import FluidSynth

load_dotenv()

class Skitz:
    def __init__(self):
        # Load OpenAI API key from environment variables
        openai.api_key = os.getenv('OPENAI_API_KEY')

        # Check if directories exist, if not, create them
        self.base_path = os.path.dirname(os.path.abspath(__file__))
        self.documentation_path = os.path.join(self.base_path, 'Documentations')
        self.inspiration_path = os.path.join(self.base_path, 'Inspirations')
        self.generations_path = os.path.join(self.base_path, 'Generations')

        os.makedirs(self.documentation_path, exist_ok=True)
        os.makedirs(self.inspiration_path, exist_ok=True)
        os.makedirs(self.generations_path, exist_ok=True)

        # Read instructions from file
        with open(os.path.join(self.documentation_path, 'instructions.md'), 'r') as file:
            self.instructions = file.read()

        # Load inspiration content
        self.inspiration = self.load_inspiration()

    def load_inspiration(self):
        # Load inspiration from file if it exists, otherwise return an empty string
        try:
            with open(os.path.join(self.inspiration_path, 'inspiration.md'), 'r') as file:
                inspiration = file.read()
                return inspiration
        except FileNotFoundError:
            print("The inspiration file is not found, continuing with the program...")
            return ""


    def extract_markdown(self, song):
        # Split the song into lines
        lines = song.split('\n')

        # Find the start and end of the markdown content
        start = None
        end = None
        for i, line in enumerate(lines):
            if line.strip() == '```':
                if start is None:
                    start = i
                else:
                    end = i
                    break

        # Extract the markdown content
        if start is not None and end is not None:
            markdown = '\n'.join(lines[start+1:end])
        else:
            markdown = song

        return markdown

    def quality_check(self, song, user_instructions):
        prompt = f"Check this output and see if it is in the correct ABC syntax. If not, change it so that it is. Here is the output: \n{song}"

        try:
            response = openai.ChatCompletion.create(
                model="gpt-4",
                messages=[
                    {"role": "system", "content": f"You are a helpful assistant. You check and correct the format/syntax of a song. Here is the ABC documentation:\n{self.instructions} & here is the user's instructions:\n{user_instructions}. Make sure the users instructions are being followed."},
                    {"role": "user", "content": prompt},
                ]
            )
        except openai.OpenAIError as e:
            print(f"\nAn error occurred: {e}")
            return None

        corrected_song = response.choices[0].message['content']

        return corrected_song

    def compose_song(self, user_instructions):
        prompt = f"# ABC Player Specification\n\nUse these instructions to complete the request only respond with ABC format:\n\n{user_instructions}\n\nInspiration:\n{self.inspiration}"
        promptNO = f"When you see a set of prompts asking for details like the genre, tempo, lyrics, chord progression, length, structure, mood, story, key, meter, note length, composer, and title of a song, use these inputs to generate a song in ABC Syntax. Use the given inputs to decide the nature of the melody, rhythm, and lyrics. Take care to respect the specific requirements provided, such as the desired emotion or the story that needs to be told through the song. Ensure that the structure is followed (if specified), and that the result is in accordance with the specified key and meter. Reflect the desired length in the overall structure and progression of the song. Place the specified composer's name and the song title appropriately in the ABC notation.   \n\nInspiration:\n{self.inspiration} \n\n{user_instructions}"

        try:
            response = openai.ChatCompletion.create(
                model="gpt-4",
                messages=[
                    {"role": "system", "content": "You are a helpful assistant. You can generate creative and original music based on the input requirements given to you."},
                    {"role": "user", "content": prompt},
                ]
            )
        except openai.OpenAIError as e:
            print(f"\nAn error occurred: {e}")
            return None

        song = response.choices[0].message['content']

        # Ensure the song has a default note length
        if "L:" not in song:
            song = "L:1/8\n" + song

        # Extract the markdown content
        song = self.extract_markdown(song)

        # Perform a quality check on the output song by default
        corrected_song = self.quality_check(song, user_instructions)
        return corrected_song

    def write_abc_file(self, song, filename):
        os.makedirs("Generations", exist_ok=True)

        filepath = os.path.join("Generations", filename)
        if os.path.exists(filepath):
            overwrite = input(f"\nA file with the name {filename} already exists. Do you want to overwrite it? (y/n): ")
            if overwrite.lower() != 'y':
                return

        with open(filepath, 'w') as file:
            file.write(song)

        return filepath

    def convert_to_midi(self, abc_file, midi_file):
        # Convert ABC to MIDI using music21
        abcScore = converter.parse(abc_file)
        midiScore = abcScore.write('midi', midi_file)

    def convert_to_audio(self, midi_file, audio_file):
        # Convert MIDI to audio using FluidSynth
        fs = FluidSynth()
        fs.midi_to_audio(midi_file, audio_file)

    def get_user_input_easy(self):
        user_instructions = ""
        questions = [
            "\nPlease enter the genre of the song: ",
            "\nPlease enter the tempo of the song: ",
            "\nPlease enter any specific lyrics or themes you'd like to include: ",
            "\nPlease enter the desired chord progression: ",
            "\nPlease enter any additional instructions or preferences: ",
            "\nPlease enter the desired length of the song (short, medium, long): ",
            "\nDo you want the song to have a specific structure (verse, chorus, bridge, etc.)? If so, please specify: ",
            "\nDo you want the song to have a specific mood or emotion? If so, please specify: ",
            "\nDo you want the song to tell a story? If so, please briefly describe the story: ",
             "\nDo you want to perform a quality check on the output? (yes/no): ",
        ]

        for question in questions:
            answer = input(question)
            user_instructions += answer + "\n"

        return user_instructions.strip()

    def get_user_input_advanced(self):
        user_instructions_advanced = ""
        questions = [
            "\nPlease enter the genre of the song: ",
            "\nPlease enter the tempo of the song: ",
            "\nPlease enter any specific lyrics or themes you'd like to include: ",
            "\nPlease enter the desired chord progression: ",
            "\nPlease enter any additional instructions or preferences: ",
            "\nPlease enter the desired length of the song (short, medium, long): ",
            "\nDo you want the song to have a specific structure (verse, chorus, bridge, etc.)? If so, please specify: ",
            "\nDo you want the song to have a specific mood or emotion? If so, please specify: ",
            "\nDo you want the song to tell a story? If so, please briefly describe the story: ",
            "\nPlease enter the key of the song: ",
            "\nPlease enter the meter of the song: ",
            "\nPlease enter the default length of a note: ",
            "\nPlease enter the composer of the song: ",
            "\nPlease enter the title of the song: ",
            "\nDo you want to perform a quality check on the output? (yes/no): ",
        ]

    

        for question in questions:
            answer = input(question)
            user_instructions_advanced += answer + "\n"

        return user_instructions_advanced.strip()

    def generate_song(self):
        print("\n")
        print("""
                █████████████████████████████████████████████████████
                █░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░█
                █░░░▄▄▄░░░░░▄▄▄▄▄▄░░░░▄▄▄░░▄▄▄░░░░░░░▄▄░░░░▄▄▄░░░█
                █░░░███░░░░██░░░░██░░░███░░███░░░░░░░███░░░███░░░█
                █░░░███░░░░██░░▄▄▄██░░░███░░▄▄▄░░░░░░░███░░░███░░░█
                █░░░███░░░░██░░░░██░░░███░░░░██░░░░░░░███░░░░░░░░█
                █░░░▀▀▀░░░░▀▀▀▀▀▀░░░░▀▀▀░░░░░▀▀▀░░░░░░░▀▀░░░░▀▀▀░░█
                █░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░█
                █████████████████████████████████████████████████████

        """)
        print("\nWelcome to Skitz! This program will generate a song for you based on your input.")
        
        mode = input("Please select a mode: \n1. Easy \n2. Advanced\n")
        
        if mode == '1':
            user_instructions = self.get_user_input_easy()
        elif mode == '2':
            user_instructions = self.get_user_input_advanced()
        else:
            print("Invalid mode selected. Please try again.")
            return

        print("\nGenerating your song. This may take a few moments...")
        song = self.compose_song(user_instructions)

        if song is None:
            print("\nFailed to generate a song. Please try again.")
            return

        filename = f"{user_instructions[:20].replace(' ', '_')}.abc"

        filepath = self.write_abc_file(song, filename)

        if filepath:
            print(f"\nThe song has been written to: {filepath}")
            # # Convert ABC to MIDI
            # midi_file = filename.replace('.abc', '.midi')
            # self.convert_to_midi(filepath, midi_file)

            # # Convert MIDI to audio
            # audio_file = filename.replace('.abc', '.mp3')
            # self.convert_to_audio(midi_file, audio_file)

            # print(f"\nThe song has been converted to audio and saved as: {audio_file}")
        else:
            print("\nFailed to write the song to a file. Please try again.")


if __name__ == "__main__":
    skitz = Skitz()
    skitz.generate_song()
