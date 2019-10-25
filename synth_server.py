# -*- coding: utf-8 -*-
# /usr/bin/python2


from __future__ import print_function

import os

import numpy as np
import tensorflow as tf
# from graphs import Graph
from utils import *
from data_load import load_vocab, phones_normalize, text_normalize
from scipy.io.wavfile import write
from tqdm import tqdm

## to import configs
HERE = os.path.realpath(os.path.abspath(os.path.dirname(__file__)))
sys.path.append( HERE + '/script/' )

import imp
import codecs
import glob
import timeit 
import time
import os
import stat
from argparse import ArgumentParser



from configuration import load_config
from synthesize import restore_archived_model_parameters, restore_latest_model_parameters, \
                        get_text_lengths, encode_text, synth_codedtext2mel, synth_mel2mag, \
                        synth_wave
from expand_digits import norm_hausa
from festival.flite import get_flite_phonetisation

from architectures import Text2MelGraph, SSRNGraph

def file_age_in_seconds(pathname):
    return time.time() - os.stat(pathname)[stat.ST_MTIME]

def start_clock(comment):
    print ('%s... '%(comment)),
    return (timeit.default_timer(), comment)

def stop_clock((start_time, comment), width=40):
    padding = (width - len(comment)) * ' '
    print ('%s--> took %.2f seconds' % (padding, (timeit.default_timer() - start_time)) )



class Synthesiser(object):
    def __init__(self, hp, t2m_epoch=-1, ssrn_epoch=-1):

        #assert hp.vocoder=='griffin_lim', 'Other vocoders than griffin_lim not yet supported'
        assert hp.vocoder in ['griffin_lim', 'world'], 'Other vocoders than griffin_lim/world not yet supported'


        self.hardlimit = 1000000000 ## number of time steps

        self.char2idx, idx2char = load_vocab(hp)

        # Load graph
        self.hp = hp
        
        self.g1 = Text2MelGraph(hp, mode="synthesize"); print("Graph 1 (t2m) loaded")
        self.g2 = SSRNGraph(hp, mode="synthesize"); print("Graph 2 (ssrn) loaded")

        self.sess = tf.Session()
    
        self.sess.run(tf.global_variables_initializer())

        # Restore parameters
        if t2m_epoch > -1:
            restore_archived_model_parameters(self.sess, hp, 't2m', t2m_epoch)
        else:
            t2m_epoch = restore_latest_model_parameters(self.sess, hp, 't2m')

        if ssrn_epoch > -1:    
            restore_archived_model_parameters(self.sess, hp, 'ssrn', ssrn_epoch)
        else:
            ssrn_epoch = restore_latest_model_parameters(self.sess, hp, 'ssrn')

        print('Finished loading synthesis model')


    def process_text(self, txtfile):
        '''
        Write this in e.g. language specific subclasses to perform
        arbitrary text norm and phonetisation
        '''
        text = codecs.open(txtfile, encoding='utf8').read()
        return text 


    def check_for_new_files_and_synth(self, direc):
        
        if not os.path.isdir(os.path.join(direc, 'archive')):
            os.makedirs(os.path.join(direc, 'archive'))

        current_files = os.listdir(direc)
        for fname in sorted(current_files):
            if fname.endswith('.txt'):
                if fname.replace('.txt','.wav') not in current_files:

                    txtfile = os.path.join(direc, fname)
                    outfile = txtfile.replace('.txt','.wav')
                    # text = codecs.open(txtfile, encoding='utf8').read()
                    text = self.process_text(txtfile)
                    os.system('mv %s %s/archive/'%(txtfile, direc))

                    

                    self.synthesise(text, outfile)



    def remove_old_wave_files(self, direc, threshold=300): ## 300 seconds = 5 min
        for fname in glob.glob(direc + '/*.wav'):
            age = file_age_in_seconds(fname)
            if age > threshold:
                print ('           remove %s, age %s seconds'%(fname, age))
                os.system('rm %s'%(fname))


    def synthesise(self, text, outfile):

        text = self.process_text(text)

        if self.hp.input_type=='letters':
            textin = text_normalize(text, self.hp)
        elif self.hp.input_type=='phones':
            textin = phones_normalize(text, self.char2idx)
        else:
            sys.exit('visbfboer8')

        textin = [self.char2idx[char] for char in textin]

        ## text to int array of appropriate length and dummy batch dimension
        stacked_text = np.zeros((1, self.hp.max_N), np.int32)
        if len(textin) >  self.hp.max_N:
            textin = textin[:self.hp.max_N]
            print('warning: text too long - trim end!')
        stacked_text[0, :len(textin)] = textin
        L = stacked_text

        text_lengths = get_text_lengths(L)


        K, V = encode_text(self.hp, L, self.g1, self.sess)
        Y, lengths, alignments = synth_codedtext2mel(self.hp, K, V, text_lengths, self.g1, self.sess)

        Z = synth_mel2mag(self.hp, Y, self.g2, self.sess)


        assert self.hp.vocoder in ['griffin_lim', 'world'], 'Other vocoders than griffin_lim/world not yet supported'


        mag = Z[0,:,:]  ### first item in batch is spectrogram
        mag = mag[:lengths[0]*self.hp.r,:]  ### trim to generated length

        synth_wave(self.hp, mag, outfile)




class HausaSynthesiser(Synthesiser):
    def process_text(self, txtfile):
        text = codecs.open(txtfile, encoding='utf8').read()
        try:
            norm_text = norm_hausa(text)
        except:
            norm_text = text 
        return norm_text


class CMULexSynthesiser(Synthesiser):
    def process_text(self, txtfile):
        #sys.exit('licbnwsdibvilsfblv')

        phones = get_flite_phonetisation(txtfile, dictionary='cmulex')    
        print (phones)
        sys.exit('licbnwsdibvilsfblv')


def main_work():

    #################################################
      
    # ============= Process command line ============

    a = ArgumentParser()
    a.add_argument('-c', dest='config', required=True, type=str)
    a.add_argument('-dir', dest='synthdir', required=True, type=str)
    a.add_argument('-limit', default=0, type=int)    
    opts = a.parse_args()
    
    # ===============================================
    
    hp = load_config(opts.config)

    hp.language = 'en_cmulex'

    if hp.language=='en_cmulex':
        s = CMULexSynthesiser(hp)
    elif hp.language=='hausa':
        s = HausaSynthesiser(hp)
    else:
        s = Synthesiser(hp)

    if opts.limit:
        s.hardlimit = opts.limit

    if 1: ## for debugging
        os.system('echo "The fish twisted and turned." > /tmp/test.txt')
        s.synthesise('/tmp/test.txt', '/disk/scratch/script_project/newshack/testsynth3/utt01.wav')
        # s.synthesise('<_START_> dh ax <> b er ch <> k ax n uw <> s l ih d <> aa n <> dh ax <> s m uw dh <> p l ae ng k s <.> <_END_>', \
                # '/disk/scratch/script_project/newshack/testsynth3/utt01.wav') # '/group/project/script_tts/data/synth_service')
        # s.synthesise('<_START_> D @ <> f I S <> t w I s t I d <> a n d <> t @@ n d <.> <_END_>', '/disk/scratch/script_project/newshack/testsynth3') # '/group/project/script_tts/data/synth_service')
        #s.synthesise(u'The fish twisted and turned.', '/group/project/script_tts/data/synth_service/test.wav')
        sys.exit('qlebfcwivbrev88888')

    try:
        while True:
            s.remove_old_wave_files(opts.synthdir)
            s.check_for_new_files_and_synth(opts.synthdir)
            os.system('sleep 0.5')
            os.system('date')
            print('Listening for new .txt files with no .wav associated at %s'%(opts.synthdir))
            #print ('!')
    except KeyboardInterrupt:
        pass




if __name__=="__main__":

    main_work()