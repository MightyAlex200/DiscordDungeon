from story.story_manager import *
from generator.gpt2.gpt2_generator import *



def console_print(text, width=75):
    last_newline = 0
    i = 0
    while i < len(text):
        if text[i] == "\n":
            last_newline = 0
        elif last_newline > width:
            text = text[:i] + "\n" + text[i:]
        else:
            last_newline += 1
        i += 1


def play_unconstrained():

    print("Initializing AI Dungeon! (This might take a few minutes)")
    generator = GPT2Generator()
    prompt = get_story_start("knight")
    context = get_context("knight")
    print("DEUBUG: Context is ", context)
    print("DEBUG: Prompt is ", prompt)
    story_manager = UnconstrainedStoryManager(generator)
    print("Generating initial story.")
    story_manager.start_new_story(prompt, context=context)

    with open('opening.txt', 'r') as file:
        starter = file.read()

    print(starter)

    print("\n")
    console_print(context)
    console_print(str(story_manager.story))
    while True:
        action = input("> ")

        if action != "":
            action = action.strip()

            action = action[0].upper() + action[1:]

            action = "\n> " + action + "\n"
            action = remove_profanity(action)
            # action = first_to_second_person(action)

        result = story_manager.act(action)
        if player_died(result):
            console_print(result + "\nGAME OVER")
            break
        else:
            console_print(result)


if __name__ == '__main__':
    play_unconstrained()

