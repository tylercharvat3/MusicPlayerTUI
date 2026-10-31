import pygame

pygame.mixer.init()
offset_ms = 0  # where the current playback started, in ms
current_song = None

def play(song=current_song):
    global offset_ms,current_song

    if pygame.mixer.music.get_busy():
        #check if SONG is different from curr song
        if(song != current_song):
            #play new song
            current_song = song
            offset_ms = 0
            pygame.mixer.music.load(song)
            pygame.mixer.music.play()
            return True
        else:
            #pause
            offset_ms += pygame.mixer.music.get_pos()   # accumulate, don't replace
            pygame.mixer.music.pause()
            return False
    else:
        current_song = song
        pygame.mixer.music.load(song)
        pygame.mixer.music.play(start=offset_ms / 1000)  # seconds
        return True


    