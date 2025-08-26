import React, { useState, useEffect } from 'react';
import {
  StyleSheet,
  View,
  Text,
  ScrollView,
  SafeAreaView,
  KeyboardAvoidingView,
  Platform,
  Image,
  Alert
} from 'react-native';
import { useRouter } from 'expo-router';
import InputField from '@/components/InputField';
import Button from '@/components/Button';
import FolderPicker from '@/components/FolderPicker';
import BulkSaveModal from '@/components/BulkSaveModal';
import { useStore } from '@/store';
import {
  isValidUrl,
  getVideoSource,
  getVideoThumbnailUrl,
  generateVideoTitle,
  getVideoMetadata
} from '@/utils/videoUtils';
import { VideoSource } from '@/types';
import { CircleCheck as CheckCircle2, Circle as XCircle, Link, File as FileEdit } from 'lucide-react-native';

export default function AddVideoScreen() {
  const router = useRouter();
  const { addVideo, folders, getFolders, initializeStorage, videos } = useStore();

  const [url, setUrl] = useState('');
  const [title, setTitle] = useState('');
  const [notes, setNotes] = useState('');
  const [folderId, setFolderId] = useState('');
  
  const [isValidating, setIsValidating] = useState(false);
  const [isUrlValid, setIsUrlValid] = useState<boolean | null>(null);
  const [videoSource, setVideoSource] = useState<VideoSource | null>(null);
  const [thumbnailUrl, setThumbnailUrl] = useState<string | null>(null);
  
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [videoMetadata, setVideoMetadata] = useState<any>(null);
  const [showBulkSaveModal, setShowBulkSaveModal] = useState(false);

  useEffect(() => {
    const initializeFolders = async () => {
      await getFolders();
      if (folders.length === 0) {
        await initializeStorage();
        await getFolders();
      }
    };
    initializeFolders();
  }, []);

  // フォルダの初期化とデフォルト選択
  useEffect(() => {
    if (folders.length > 0 && !folderId) {
      setFolderId(folders[0].id);
    }
  }, [folders]);

  const validateUrl = async () => {
    setIsValidating(true);
    setError(null);
    
    if (!url.trim()) {
      setError('URLを入力してください');
      setIsValidating(false);
      setIsUrlValid(false);
      return;
    }
    
    const valid = isValidUrl(url);
    setIsUrlValid(valid);
    
    if (valid) {
      const source = getVideoSource(url);
      setVideoSource(source);
      
      try {
        const metadata = await getVideoMetadata(url);
        if (metadata) {
          setVideoMetadata(metadata);
          setThumbnailUrl(metadata.thumbnailUrl);
          if (!title) {
            setTitle(metadata.title);
          }
        }
      } catch (error) {
        console.error('Error fetching video metadata:', error);
        setError('動画情報の取得に失敗しました');
      }
    } else {
      setError('有効なURLではありません');
      setVideoSource(null);
      setThumbnailUrl(null);
    }
    
    setIsValidating(false);
  };

  const handleSubmit = async () => {
    setError(null);
    
    if (!isUrlValid) {
      setError('有効なURLを入力してください');
      return;
    }
    
    if (!title.trim()) {
      setError('タイトルを入力してください');
      return;
    }
    
    if (!folderId) {
      setError('フォルダを選択してください');
      return;
    }
    
    setIsSubmitting(true);
    
    try {
      // 条件分岐: InstagramのURLかどうかを判定
      if (url.toLowerCase().includes('instagram.com')) {
        // Ifブロック: InstagramのURLの場合
        try {
          // API呼び出し (Instagramメタデータ取得)
          const response = await fetch('https://d9431e70-f6fe-4eb6-9a36-21f141639f26-00-3ks681ngz8cyf.sisko.replit.dev/api/get-metadata', {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
            },
            body: JSON.stringify({ url }),
          });

          if (!response.ok) {
            throw new Error('Instagram動画情報の取得に失敗しました');
          }

          const instagramMetadata = await response.json();

          // API成功時 → データベースに保存
          await addVideo({
            url,
            title: instagramMetadata.title || title,
            thumbnailUrl: instagramMetadata.thumbnailUrl || getVideoThumbnailUrl(url),
            source: VideoSource.Instagram,
            notes,
            folderId,
            videoTitle: instagramMetadata.title || '',
            videoAuthorName: instagramMetadata.authorName || '',
            videoAuthorIconUrl: null, // 外部APIではアイコンURLは取得不可のため
          });

          // 完了処理
          Alert.alert(
            '成功',
            'Instagramの動画を保存しました',
            [
              {
                text: 'コレクションに戻る',
                onPress: () => router.push('/(tabs)'),
              },
              {
                text: '続けて追加',
                style: 'cancel',
              },
            ]
          );
        } catch (instagramError) {
          // エラーハンドリング
          console.error('Instagram API error:', instagramError);
          setError('Instagram動画の情報取得に失敗しました。手動でタイトルを入力して保存してください。');
          
          // フォールバック: 手動入力されたタイトルで保存
          await addVideo({
            url,
            title,
            thumbnailUrl: getVideoThumbnailUrl(url),
            source: VideoSource.Instagram,
            notes,
            folderId,
            videoTitle: title,
            videoAuthorName: '',
            videoAuthorIconUrl: null,
          });

          Alert.alert(
            '保存完了',
            '動画を保存しました（メタデータの自動取得は失敗しましたが、手動入力の情報で保存されました）',
            [
              {
                text: 'コレクションに戻る',
                onPress: () => router.push('/(tabs)'),
              },
              {
                text: '続けて追加',
                style: 'cancel',
              },
            ]
          );
        }
      } else {
        // Elseブロック: Instagram以外のURLの場合（従来の処理）
        await addVideo({
          url,
          title,
          thumbnailUrl: videoMetadata?.thumbnailUrl || getVideoThumbnailUrl(url),
          source: videoSource || VideoSource.Other,
          notes,
          folderId,
          videoTitle: videoMetadata?.title || '',
          videoAuthorName: videoMetadata?.authorName || '',
          videoAuthorIconUrl: videoMetadata?.authorIconUrl || null,
        });

        Alert.alert(
          '成功',
          '動画が保存されました',
          [
            {
              text: 'コレクションに戻る',
              onPress: () => router.push('/(tabs)'),
            },
            {
              text: '続けて追加',
              style: 'cancel',
            },
          ]
        );
      }
      
      setUrl('');
      setTitle('');
      setNotes('');
      setIsUrlValid(null);
      setVideoSource(null);
      setThumbnailUrl(null);
      setVideoMetadata(null);
    } catch (err) {
      setError('動画の保存に失敗しました。もう一度お試しください。');
    } finally {
      setIsSubmitting(false);
    }
  };

  // 新API(v2)テスト用の保存処理
  const handleTestNewApiSubmit = async () => {
    console.log('[DEBUG] handleTestNewApiSubmit: Starting new API test');
    setError(null);
    
    // Instagram/YouTube URLの条件分岐チェック
    const isInstagram = url.toLowerCase().includes('instagram.com');
    const isYouTube = url.toLowerCase().includes('youtube.com') || url.toLowerCase().includes('youtu.be');
    const isTikTok = url.toLowerCase().includes('tiktok.com');
    
    if (!isInstagram && !isYouTube && !isTikTok) {
      setError('新APIテストはInstagram・YouTube・TikTokのURLのみ対応しています');
      return;
    }
    
    if (!isUrlValid) {
      setError('有効なURLを入力してください');
      return;
    }
    
    if (!title.trim()) {
      setError('タイトルを入力してください');
      return;
    }
    
    if (!folderId) {
      setError('フォルダを選択してください');
      return;
    }
    
    setIsSubmitting(true);
    
    try {
      console.log('[DEBUG] handleTestNewApiSubmit: Calling new API v2');
      
      console.log('[DEBUG] Sending URL to new API v2:', url);
      
      // 新API(v2)への呼び出し
      const response = await fetch('https://d9431e70-f6fe-4eb6-9a36-21f141639f26-00-3ks681ngz8cyf.sisko.replit.dev/api/v2/get-metadata', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ url }),
      });

      if (!response.ok) {
        throw new Error('新API(v2)での動画情報取得に失敗しました');
      }

      const apiResponse = await response.json();
      console.log('[DEBUG] handleTestNewApiSubmit: API response:', apiResponse);

      // unique_video_idによる重複チェック
      if (apiResponse.unique_video_id) {
        console.log('[DEBUG] handleTestNewApiSubmit: Checking for duplicates with unique_video_id:', apiResponse.unique_video_id);
        
        const existingVideos = videos.filter(video => 
          video.uniqueVideoId === apiResponse.unique_video_id
        );
        
        if (existingVideos.length > 0) {
          const existingVideo = existingVideos[0];
          const existingFolder = folders.find(f => f.id === existingVideo.folderId);
          
          const duplicateMessage = `この動画は既に「${existingFolder?.name || '未分類'}」に保存されています`;
          
          if (Platform.OS === 'web') {
            window.alert(duplicateMessage);
          } else {
            Alert.alert('重複エラー', duplicateMessage);
          }
          return;
        }
      }

      // データベースに保存
      await addVideo({
        url,
        title: apiResponse.title || title,
        thumbnailUrl: apiResponse.thumbnailUrl || getVideoThumbnailUrl(url),
        source: isInstagram ? VideoSource.Instagram : isYouTube ? VideoSource.YouTube : VideoSource.TikTok,
        notes,
        folderId,
        videoTitle: apiResponse.title || '',
        videoAuthorName: apiResponse.authorName || '',
        videoAuthorIconUrl: null,
        uniqueVideoId: apiResponse.unique_video_id || null,
      });

      // 成功通知
      Alert.alert(
        '【テスト成功】',
        '新APIでの保存が完了しました',
        [
          {
            text: 'コレクションに戻る',
            onPress: () => router.push('/(tabs)'),
          },
          {
            text: '続けて追加',
            style: 'cancel',
          },
        ]
      );
      
      // フォームをクリア
      setUrl('');
      setTitle('');
      setNotes('');
      setIsUrlValid(null);
      setVideoSource(null);
      setThumbnailUrl(null);
      setVideoMetadata(null);
    } catch (err) {
      console.error('[DEBUG] handleTestNewApiSubmit: Error:', err);
      setError(`新APIテストでエラーが発生しました: ${err instanceof Error ? err.message : 'Unknown error'}`);
    } finally {
      setIsSubmitting(false);
    }
  };

  // Debug log for button disabled state
  console.log('[DEBUG] Button disabled check:', {
    currentUrl: url,
    isUrlValidState: isUrlValid,
    includesInstagram: url.toLowerCase().includes('instagram.com'),
    includesYoutube: url.toLowerCase().includes('youtube.com'),
    includesYoutuBe: url.toLowerCase().includes('youtu.be'),
    includesTikTok: url.toLowerCase().includes('tiktok.com'),
    urlConditionCheck: url.toLowerCase().includes('instagram.com') || url.toLowerCase().includes('youtube.com') || url.toLowerCase().includes('youtu.be') || url.toLowerCase().includes('tiktok.com'),
    disabledCondition: !isUrlValid || !(url.toLowerCase().includes('instagram.com') || url.toLowerCase().includes('youtube.com') || url.toLowerCase().includes('youtu.be') || url.toLowerCase().includes('tiktok.com'))
  });

  return (
    <SafeAreaView style={styles.container}>
      <KeyboardAvoidingView
        behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
        style={styles.container}
      >
        <ScrollView 
          contentContainerStyle={styles.scrollContainer}
          keyboardShouldPersistTaps="handled"
        >
            <View style={styles.header}>
              <Text style={styles.title}>新しい料理動画を追加</Text>
              <Text style={styles.subtitle}>
                YouTubeやTikTokなどのレシピ動画を保存できます
              </Text>
            </View>
            
            <Button
              title="複数の動画を一括保存"
              variant="secondary"
              onPress={() => setShowBulkSaveModal(true)}
              style={styles.bulkSaveButton}
            />
            
            {error && <Text style={styles.errorText}>{error}</Text>}
            
            <View style={styles.formSection}>
              <View style={styles.sectionHeader}>
                <Link size={20} color="#FF9494" />
                <Text style={styles.sectionTitle}>動画URL</Text>
              </View>
              
              <View style={styles.urlInputContainer}>
                <View style={styles.inputWrapper}>
                  <InputField
                    label="動画のURL"
                    placeholder="https://youtube.com/watch?v=..."
                    value={url}
                    onChangeText={setUrl}
                    autoCapitalize="none"
                    keyboardType="url"
                  />
                </View>
                
                <Button
                  title="URLを確認"
                  variant="secondary"
                  onPress={validateUrl}
                  isLoading={isValidating}
                  style={styles.validateButton}
                />
              </View>
              
              {isUrlValid !== null && (
                <View style={styles.validationResult}>
                  {isUrlValid ? (
                    <>
                      <CheckCircle2 size={16} color="#4CAF50" />
                      <Text style={styles.validUrlText}>
                        有効なURL ({videoSource})
                      </Text>
                    </>
                  ) : (
                    <>
                      <XCircle size={16} color="#FF5252" />
                      <Text style={styles.invalidUrlText}>
                        無効なURL
                      </Text>
                    </>
                  )}
                </View>
              )}
              
              {thumbnailUrl && (
                <Image
                  source={{ uri: thumbnailUrl }}
                  style={styles.thumbnail}
                  resizeMode="cover"
                />
              )}
            </View>
            
            <View style={styles.formSection}>
              <View style={styles.sectionHeader}>
                <FileEdit size={20} color="#FF9494" />
                <Text style={styles.sectionTitle}>詳細情報</Text>
              </View>
              
              <InputField
                label="タイトル"
                placeholder="動画のタイトルを入力"
                value={title}
                onChangeText={setTitle}
              />
              
              <InputField
                label="レシピメモ (任意)"
                placeholder="調理のコツや材料リストなどを入力"
                value={notes}
                onChangeText={setNotes}
                multiline
                numberOfLines={4}
                style={styles.notesInput}
              />
              
              <FolderPicker
                label="保存先フォルダ"
                folders={folders}
                selectedFolderId={folderId}
                onValueChange={setFolderId}
              />
            </View>
            
            <Button
              title="保存する"
              onPress={handleSubmit}
              isLoading={isSubmitting}
              disabled={!isUrlValid}
              style={styles.submitButton}
            />
            
            <Button
              title="（テスト用）新APIで保存"
              variant="secondary"
              onPress={handleTestNewApiSubmit}
              isLoading={isSubmitting}
              disabled={!isUrlValid || !(url.toLowerCase().includes('instagram.com') || url.toLowerCase().includes('youtube.com') || url.toLowerCase().includes('youtu.be') || url.toLowerCase().includes('tiktok.com'))}
              style={[styles.submitButton, styles.testButton]}
            />
        </ScrollView>
        
        <BulkSaveModal
          visible={showBulkSaveModal}
          onClose={() => setShowBulkSaveModal(false)}
        />
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#FAFAFA',
  },
  scrollContainer: {
    flexGrow: 1,
    paddingHorizontal: 16,
    paddingTop: 16,
    paddingBottom: 40,
  },
  header: {
    marginBottom: 24,
  },
  title: {
    fontSize: 24,
    fontWeight: 'bold',
    color: '#1F1F1F',
    marginBottom: 8,
  },
  subtitle: {
    fontSize: 14,
    color: '#6B6B6B',
  },
  bulkSaveButton: {
    marginBottom: 16,
  },
  errorText: {
    color: '#FF5252',
    marginBottom: 16,
    padding: 12,
    backgroundColor: '#FFEEEE',
    borderRadius: 8,
  },
  formSection: {
    backgroundColor: 'white',
    borderRadius: 16,
    padding: 20,
    marginBottom: 24,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.05,
    shadowRadius: 4,
    elevation: 2,
  },
  sectionHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 20,
  },
  sectionTitle: {
    fontSize: 18,
    fontWeight: '600',
    color: '#1F1F1F',
    marginLeft: 8,
  },
  urlInputContainer: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 12,
  },
  inputWrapper: {
    flex: 1,
  },
  validateButton: {
    marginTop: 24,
  },
  validationResult: {
    flexDirection: 'row',
    alignItems: 'center',
    marginTop: 12,
    marginBottom: 16,
    padding: 8,
    backgroundColor: '#F8F8F8',
    borderRadius: 8,
  },
  validUrlText: {
    color: '#4CAF50',
    marginLeft: 8,
    fontSize: 14,
  },
  invalidUrlText: {
    color: '#FF5252',
    marginLeft: 8,
    fontSize: 14,
  },
  thumbnail: {
    width: '100%',
    height: 180,
    borderRadius: 12,
    marginTop: 16,
  },
  notesInput: {
    height: 120,
    textAlignVertical: 'top',
  },
  submitButton: {
    marginTop: 8,
  },
  testButton: {
    backgroundColor: '#FFA500',
    borderColor: '#FFA500',
    marginTop: 8,
  },
});