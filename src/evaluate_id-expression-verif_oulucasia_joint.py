

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import tensorflow as tf
import numpy as np
import argparse
import facenet
import lfw
import os
import sys
import math
from sklearn.decomposition import PCA
import time
from sklearn import metrics
from scipy.optimize import brentq
from scipy import interpolate
from datetime import datetime
import matplotlib.pyplot as plt
from itertools import islice
import shutil

sys.path.append('../util')
import  save_false_images

def main(args):

    subdir = datetime.strftime(datetime.now(), '%Y%m%d-%H%M%S')
    log_dir = os.path.join(os.path.expanduser(args.logs_base_dir), subdir)
    print('log_dir: %s\n' % log_dir)
    if not os.path.isdir(log_dir):  # Create the log directory if it doesn't exist
        os.makedirs(log_dir)
  
    with tf.Graph().as_default():
      
        with tf.Session() as sess:
            
            # Read the file containing the pairs used for testing
            #pairs = lfw.read_pairs(os.path.expanduser(args.test_pairs))
            #np.random.shuffle(pairs) ##avoid the n_same =0 or n_diff=0 during crossvalidation
            paths = []
            actual_issame = []
            actual_isrequired = []
            labels_actual = []
            labels_require = []
            labels_ref = []
            pairs = []

            with open(os.path.expanduser(args.test_pairs),'r') as f:
                for line in islice(f, 1, None):
                    pairs.append(line)
                np.random.shuffle(pairs) ##avoid the n_same =0 or n_diff=0 during crossvalidation
           
            for pair in pairs:   
                 [cnt, img, img_ref, issame, expr_actual, expr_require, expr_ref, expre_isrequire] = str.split(pair)
                 paths.append(img)
                 paths.append(img_ref)
                 issame = True if issame=='True' else False
                 actual_issame.append(issame)
                 expre_isrequire = True if expre_isrequire == 'True' else False
                 actual_isrequired.append(expre_isrequire)
                 labels_actual.append(int(expr_actual))
                 labels_require.append(int(expr_require))
                 labels_ref.append(int(expr_ref))
  
            # Load the model
            print('Model directory: %s' % args.model_dir)
            meta_file, ckpt_file = facenet.get_model_filenames(os.path.expanduser(args.model_dir))

            print('Metagraph file: %s' % meta_file)
            print('Checkpoint file: %s' % ckpt_file)
            facenet.load_model(args.model_dir, meta_file, ckpt_file)

            if not args.features_dir:

                # Get input and output tensors
                #images_placeholder = tf.get_default_graph().get_tensor_by_name("image_batch:0")
                images_placeholder = tf.get_default_graph().get_tensor_by_name("input:0")
                embeddings = tf.get_default_graph().get_tensor_by_name("embeddings:0")
                keep_probability_placeholder = tf.get_default_graph().get_tensor_by_name('keep_probability:0')
                #weight_decay_placeholder = tf.get_default_graph().get_tensor_by_name('weight_decay:0')
                phase_train_placeholder = tf.get_default_graph().get_tensor_by_name('phase_train:0')
                phase_train_placeholder_expression = tf.get_default_graph().get_tensor_by_name('phase_train_expression:0')

                logits = tf.get_default_graph().get_tensor_by_name('logits_expr:0')
                image_size = images_placeholder.get_shape()[1]
                embedding_size = embeddings.get_shape()[1]

                # Run forward pass to calculate embeddings
                print('Runnning forward pass on input images')
                batch_size = args.lfw_batch_size
                nrof_images = len(paths)
                nrof_batches = int(math.ceil(1.0*nrof_images / batch_size))
                emb_array = np.zeros((nrof_images, embedding_size))
                #emb_array = np.zeros((2*batch_size, embedding_size))
                logits_size = logits.get_shape()[1]
                logits_array = np.zeros((nrof_images, logits_size), dtype=float)
                for i in range(nrof_batches):
                    print("Test batch:%d/%d\n"%(i,nrof_batches))
                    start_index = i*batch_size
                    end_index = min((i+1)*batch_size, nrof_images)
                    paths_batch = paths[start_index:end_index]
                    images = facenet.load_data(paths_batch, False, False, image_size)
                    feed_dict = {phase_train_placeholder: False, phase_train_placeholder_expression: False, images_placeholder:images, keep_probability_placeholder:1.0}
                    #feed_dict = {phase_train_placeholder: False, images_placeholder: images}
                    emb_, logits_ = sess.run([embeddings, logits], feed_dict=feed_dict)
                    emb_array[start_index:end_index,:] = emb_
                    logits_array[start_index:end_index,:] = logits_

                #np.save(os.path.join(log_dir, 'features.npy'), emb_array)
            else:
                emb_array = np.load(args.feature_dir)


            print('Evaluate_model: %s' % args.evaluate_mode)
            ### Expression evaluation #######
            logits_array_input = logits_array[0::2] #don't need references images
            express_probs = np.exp(logits_array_input) / np.tile(np.reshape(np.sum(np.exp(logits_array_input), 1),(logits_array_input.shape[0], 1)), (1, logits_array_input.shape[1]))
            #nrof_expression = express_probs.shape[1]
            expressions_predict = np.argmax(express_probs, 1)
            correct_prediction = np.equal(expressions_predict, labels_actual)
            test_expr_acc = np.mean(correct_prediction)
            print('Expression recognition acc: %2.3f'%test_expr_acc)
            predict_isrequire_expression = np.equal(expressions_predict, labels_require)
            expression_verif = np.equal(predict_isrequire_expression, actual_isrequired)
            expression_verif_acc = np.mean(expression_verif)
            print('Expression Chanllenge-Reponse acc: %2.3f'%expression_verif_acc)

            #### saving the false expression recognition images  ######
            img_false_idx = [i for i, pred in enumerate(correct_prediction) if pred==False]
            imgs_expr_false =  [[paths[i*2],expressions_predict[i], labels_actual[i]] for i in img_false_idx]
            false_img_expr_folder = os.path.join(log_dir, 'false_expression_predict_imgs')
            os.mkdir(false_img_expr_folder)
            for img_expr_false in imgs_expr_false:
                dst_dir = os.path.join(log_dir, false_img_expr_folder, str(img_expr_false[1]))
                if not os.path.exists(dst_dir):
                    os.mkdir(dst_dir)
                img = str.split(img_expr_false[0],'/')[-1]
                img = str.split(img, '.')[0]
                dstfile = os.path.join(dst_dir,img+'_pred%d'%(img_expr_false[1])+'_gt%d'%(img_expr_false[2])+'.png')
                shutil.copy(img_expr_false[0], dstfile)

            #### Evaluation Face verification #############
            if args.evaluate_mode == 'Euclidian':

                tpr, fpr, accuracy, val, val_std, far, fp_idx, fn_idx,best_threshold, val_threshold = lfw.evaluate(emb_array, actual_issame, nrof_folds=args.lfw_nrof_folds)              
            if args.evaluate_mode == 'similarity':
                #pca = PCA(whiten=True)
                pca = PCA(n_components=128)
                pca.fit(emb_array)
                emb_array_pca = pca.transform(emb_array)

                tpr, fpr, accuracy, val, val_std, far, fp_idx, fn_idx,best_threshold, val_threshold = lfw.evaluate_cosine(emb_array_pca,
                    actual_issame, nrof_folds=args.lfw_nrof_folds)
            
            
            diff = np.subtract(emb_array[0::2], emb_array[1::2])
            dist = np.sum(np.square(diff),1)
            predict_issame = np.less(dist, best_threshold)
            identity_verif = np.equal(predict_issame, actual_issame)
            identity_verif_acc = np.mean(identity_verif)
            print('Identity verification acc is : %2.3f'%identity_verif_acc)
            ############## Global Verification-Expression Accuracy  ################         
            global_predict = np.equal(expression_verif, identity_verif)
            global_acc = np.mean(global_predict)
            print('Global Verification-Expression liveness verification acc is : %2.3f'%global_acc)
            ################### edit by mzh 12012017: select the false positive/negative images ####################
            nrof_test_paths = nrof_batches * batch_size
            nrof_test_tp_pairs = sum(actual_issame[0:int(nrof_test_paths / 2)])
            nrof_test_tn_pairs = len(actual_issame[0:int(nrof_test_paths / 2)]) - nrof_test_tp_pairs
            paths_pairs = [paths[0:nrof_test_paths:2], paths[
                                                       1:nrof_test_paths:2]]  # paths_pairs shape: [2, number of pairs], each column is corresponding to a pair of images
            paths_pairs_array = np.array(paths_pairs)
            fp_images_paths = paths_pairs_array[:, fp_idx];
            fn_images_paths = paths_pairs_array[:, fn_idx];
            _, nrof_fp_pairs = fp_images_paths.shape
            _, nrof_fn_pairs = fn_images_paths.shape

            ################### edit by mzh 12012017: select the false positive/negative images ####################

            print('Accuracy: %1.3f+-%1.3f @ Best threshold %f\n' % (np.mean(accuracy), np.std(accuracy), best_threshold))
            print('Validation rate: %2.5f+-%2.5f @ FAR=%2.5f @val_threshold %f\n' % (val, val_std, far, val_threshold))

            auc = metrics.auc(fpr, tpr)
            print('Area Under Curve (AUC): %1.3f\n' % auc)
            eer = brentq(lambda x: 1. - x - interpolate.interp1d(fpr, tpr)(x), 0., 1.)
            print('Equal Error Rate (EER): %1.3f\n' % eer)


            with open(os.path.join(log_dir, 'validation_on_dataset.txt'), 'at') as f:
                print('Saving the evaluation results...\n')
                f.write('arguments: %s\n--------------------\n' % ' '.join(sys.argv))
                f.write('Identity verification acc is : %2.3f\n' % identity_verif_acc)
                f.write('Average accuracy: %1.3f+-%1.3f\n' % (np.mean(accuracy), np.std(accuracy)))
                f.write('Validation rate: %2.5f+-%2.5f @ FAR=%2.5f\n' % (val, val_std, far))
                f.write('Best threshold: %2.5f \n' % (best_threshold))
                f.write('Validation threshold: %2.5f \n' % (val_threshold))
                f.write('Area Under Curve (AUC): %1.3f\n' % auc)
                f.write('Equal Error Rate (EER): %1.3f\n' % eer)
                f.write('------------- \n')
                f.write('Expression recognition acc: %2.3f\n'%test_expr_acc)
                f.write('Expression verification acc: %2.3f\n'%expression_verif_acc)
                f.write('------------- \n')
                f.write('Global Verification-Expression liveness acc is : %2.3f\n'%global_acc)
                print('Saving the False positive pairs images ...\n ')
                f.write('False positive pairs: %d / %d -----------------------------------------\n' % ( \
                nrof_fp_pairs, nrof_test_tp_pairs))
                for i in range(nrof_fp_pairs):
                    f.write('%d %s\n' % (i, fp_images_paths[:, i]))
                print('Saving the False negative pairs images ...\n ')
                f.write('False negative pairs: %d / %d ---------------------------------------\n' % ( \
                nrof_fn_pairs, nrof_test_tn_pairs))
                for i in range(nrof_fn_pairs):
                    f.write('%d %s\n' % (i, fn_images_paths[:, i]))
            ################### edit by mzh 12012017: write the false positive/negative images to the file  ####################

            false_images_list = os.path.join(log_dir, 'validation_on_dataset.txt')
            save_dir = log_dir
            save_false_images.save_false_images(false_images_list, save_dir)

            with open(os.path.join(log_dir, 'validation_on_dataset.txt'), 'at') as f:
                print('Saving the tpr, fpr of ROC ...\n ')
                f.write('ROC: tpr, fpr ---------------------------------------------\n')
                for tp,fp in zip(tpr, fpr):
                    f.write('tpr/fpr: %f/%f\n'%(tp,fp))

            fig = plt.figure()
            plt.plot(fpr, tpr, label='ROC')
            plt.title('Receiver Operating Characteristics')
            plt.xlabel('False Positive Rate')
            plt.ylabel('True Positive Rate')
            plt.legend()
            plt.plot([0, 1], [0, 1], 'g--')
            plt.grid(True)
            #plt.show()
            fig.savefig(os.path.join(log_dir, 'roc.png'))

def plot_roc(fpr, tpr, label):
    figure = plt.figure()
    plt.plot(fpr, tpr, label=label)
    plt.title('Receiver Operating Characteristics')
    plt.xlabel('False Positive Rate')
    plt.ylabel('True Positive Rate')
    plt.legend()
    plt.plot([0, 1], [0, 1], 'g--')
    plt.grid(True)
    plt.show()

    return figure

def parse_arguments(argv):
    parser = argparse.ArgumentParser()
    
    parser.add_argument('--lfw_dir', type=str,
        help='Path to the data directory containing aligned LFW face patches.')
    parser.add_argument('--lfw_batch_size', type=int,
        help='Number of images to process in a batch in the LFW test set.', default=100)
    parser.add_argument('--model_dir', type=str,
        help='Directory containing the metagraph (.meta) file and the checkpoint (ckpt) file containing model parameters')
    parser.add_argument('--test_pairs', type=str,
        help='The file containing the pairs to use for validation.')
    parser.add_argument('--lfw_file_ext', type=str,
        help='The file extension for the LFW dataset.', default='png', choices=['jpg', 'png'])
    parser.add_argument('--lfw_nrof_folds', type=int,
        help='Number of folds to use for cross validation. Mainly used for testing.', default=10)
    parser.add_argument('--evaluate_mode', type=str,
                        help='The evaluation mode: Euclidian distance or similarity by cosine distance.', default='Euclidian')
    parser.add_argument('--logs_base_dir', type=str,
                        help='Directory where to write event logs.', default='/data/zming/logs/facenet')
    parser.add_argument('--features_dir', type=str,
                        help='Directory where to write event logs.')

    return parser.parse_args(argv)

if __name__ == '__main__':
    main(parse_arguments(sys.argv[1:]))
