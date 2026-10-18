import React, { useState, useEffect } from 'react';
import { useQuery, useMutation } from '@tanstack/react-query';
import { Loader2, CheckCircle, AlertCircle } from 'lucide-react';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Alert, AlertDescription } from '@/components/ui/alert';
import VideoUploader from './VideoUploader';
import MetadataGenerator from './MetadataGenerator';
import TranscriptionService from './TranscriptionService';
import SummaryGenerator from './SummaryGenerator';
import ThumbnailGenerator from './ThumbnailGenerator';
import KeywordSuggestions from './KeywordSuggestions';
import RelevantTextGenerator from './RelevantTextGenerator';
import SocialMediaLinks from './SocialMediaLinks';
import SchedulingFeature from './SchedulingFeature';
import AuthenticationStatus from './AuthenticationStatus';

const API_BASE_URL = (import.meta.env.VITE_API_URL?.trim() || (import.meta.env.DEV ? 'http://localhost:5000/api' : '')).replace(/\/$/, '');

async function apiFetch(path: string, options?: RequestInit) {
  if (!API_BASE_URL) throw new Error('Backend API is not configured. Set VITE_API_URL in the frontend build environment and rebuild.');
  if (import.meta.env.PROD && /localhost|127\.0\.0\.1|0\.0\.0\.0/i.test(API_BASE_URL)) {
    throw new Error('VITE_API_URL points to a local address. Configure the public HTTPS backend URL for this build.');
  }
  try { return await fetch(`${API_BASE_URL}${path}`, options); }
  catch { throw new Error(`Cannot connect to the backend at ${API_BASE_URL}. Check the deployment and CORS configuration.`); }
}

const YouTubeAutomation = () => {
  const [videoFile, setVideoFile] = useState<File | null>(null);
  const [transcription, setTranscription] = useState<string>('');
  const [summary, setSummary] = useState<string>('');
  const [relevantText, setRelevantText] = useState<string>('');
  const [metadata, setMetadata] = useState<any>(null);
  const [isAuthenticated, setIsAuthenticated] = useState<boolean>(false);
  const [uploadProgress, setUploadProgress] = useState<number>(0);
  const [uploadStatus, setUploadStatus] = useState<string>('');

  // Check authentication status
  const { data: authStatus, refetch: refetchAuth } = useQuery({
    queryKey: ['authStatus'],
    queryFn: async () => {
      const response = await apiFetch('/auth/status');
      if (!response.ok) throw new Error('Failed to check auth status');
      return response.json();
    },
    refetchInterval: 30000, // Check every 30 seconds
  });

  useEffect(() => {
    if (authStatus) {
      setIsAuthenticated(authStatus.authenticated);
    }
  }, [authStatus]);

  // Generate metadata mutation
  const generateMetadataMutation = useMutation({
    mutationFn: async (data: { text: string; topic?: string; audience?: string; style?: string }) => {
      const response = await apiFetch('/metadata/generate', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(data),
      });
      if (!response.ok) throw new Error('Failed to generate metadata');
      return response.json();
    },
    onSuccess: (data) => {
      setMetadata(data);
    },
  });

  // Upload video mutation
  const uploadVideoMutation = useMutation({
    mutationFn: async (uploadData: FormData) => {
      const response = await apiFetch('/upload/video', {
        method: 'POST',
        body: uploadData,
      });
      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.error || 'Upload failed');
      }
      return response.json();
    },
    onSuccess: (data) => {
      setUploadStatus(`Video uploaded successfully! Video ID: ${data.video_id}`);
      setUploadProgress(100);
    },
    onError: (error: Error) => {
      setUploadStatus(`Upload failed: ${error.message}`);
      setUploadProgress(0);
    },
  });

  const handleFileSelect = (file: File) => {
    setVideoFile(file);
    setUploadProgress(0);
    setUploadStatus('');
    
    // Auto-generate metadata based on filename
    const filename = file.name.replace(/\.[^/.]+$/, ""); // Remove extension
    generateMetadataMutation.mutate({
      text: `Video file: ${filename}`,
      topic: filename,
      audience: 'general',
      style: 'informative'
    });
  };

  const handleTranscriptionComplete = (newTranscription: string) => {
    setTranscription(newTranscription);
    
    // Auto-generate metadata from transcription
    if (newTranscription.trim()) {
      generateMetadataMutation.mutate({
        text: newTranscription,
        audience: 'general',
        style: 'informative'
      });
    }
  };

  const handleSummaryGenerated = (newSummary: string) => {
    setSummary(newSummary);
  };

  const handleRelevantTextGenerated = (newRelevantText: string) => {
    setRelevantText(newRelevantText);
  };

  const handleMetadataChange = (newMetadata: any) => {
    setMetadata(newMetadata);
  };

  const handleUploadVideo = async () => {
    if (!videoFile || !metadata || !isAuthenticated) {
      return;
    }

    const formData = new FormData();
    formData.append('video', videoFile);
    formData.append('title', metadata.title || 'Untitled Video');
    formData.append('description', metadata.description || '');
    formData.append('tags', metadata.tags ? metadata.tags.join(',') : '');
    formData.append('category_id', metadata.category_id || '22');
    formData.append('privacy_status', 'private'); // Default to private

    setUploadProgress(0);
    setUploadStatus('Starting upload...');
    
    uploadVideoMutation.mutate(formData);
  };

  const handleAuthenticate = async () => {
    try {
      const response = await apiFetch('/auth/login');
      const data = await response.json();
      
      if (data.auth_url) {
        // Open authentication URL in new window
        window.open(data.auth_url, 'auth', 'width=500,height=600');
        
        // Poll for authentication completion
        const pollAuth = setInterval(async () => {
          const authCheck = await refetchAuth();
          if (authCheck.data?.authenticated) {
            clearInterval(pollAuth);
            setIsAuthenticated(true);
          }
        }, 2000);
        
        // Stop polling after 5 minutes
        setTimeout(() => clearInterval(pollAuth), 300000);
      }
    } catch (error) {
      console.error('Authentication error:', error);
    }
  };

  return (
    <div className="space-y-6">
      {/* Authentication Status */}
      <AuthenticationStatus 
        isAuthenticated={isAuthenticated}
        onAuthenticate={handleAuthenticate}
      />

      <Card className="p-6 space-y-6">
        <VideoUploader onFileSelect={handleFileSelect} />
        
        {generateMetadataMutation.isPending && (
          <div className="flex items-center justify-center">
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            <span>Generating metadata...</span>
          </div>
        )}

        {generateMetadataMutation.error && (
          <Alert variant="destructive">
            <AlertCircle className="h-4 w-4" />
            <AlertDescription>
              Error generating metadata: {(generateMetadataMutation.error as Error).message}
            </AlertDescription>
          </Alert>
        )}

        {metadata && (
          <div className="space-y-6">
            <MetadataGenerator 
              metadata={metadata} 
              onMetadataChange={handleMetadataChange} 
            />
            
            <TranscriptionService 
              videoFile={videoFile} 
              onTranscriptionComplete={handleTranscriptionComplete} 
            />
            
            <SummaryGenerator 
              transcription={transcription} 
              onSummaryGenerated={handleSummaryGenerated} 
            />
            
            <RelevantTextGenerator 
              transcription={transcription} 
              summary={summary} 
              onRelevantTextGenerated={handleRelevantTextGenerated} 
            />
            
            <ThumbnailGenerator thumbnailUrl={metadata.thumbnailUrl} />
            
            <KeywordSuggestions keywords={metadata.tags || []} />
            
            <SocialMediaLinks />
            
            <SchedulingFeature />

            {/* Upload Section */}
            {isAuthenticated && videoFile && (
              <Card className="p-4">
                <h3 className="text-lg font-semibold mb-4">Upload to YouTube</h3>
                
                {uploadStatus && (
                  <Alert className={uploadStatus.includes('successfully') ? 'border-green-500' : 'border-red-500'}>
                    {uploadStatus.includes('successfully') ? (
                      <CheckCircle className="h-4 w-4" />
                    ) : (
                      <AlertCircle className="h-4 w-4" />
                    )}
                    <AlertDescription>{uploadStatus}</AlertDescription>
                  </Alert>
                )}
                
                {uploadProgress > 0 && uploadProgress < 100 && (
                  <div className="w-full bg-gray-200 rounded-full h-2.5 mb-4">
                    <div 
                      className="bg-blue-600 h-2.5 rounded-full transition-all duration-300" 
                      style={{ width: `${uploadProgress}%` }}
                    ></div>
                  </div>
                )}
                
                <Button 
                  onClick={handleUploadVideo}
                  disabled={uploadVideoMutation.isPending || !videoFile || !metadata}
                  className="w-full"
                >
                  {uploadVideoMutation.isPending ? (
                    <>
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      Uploading...
                    </>
                  ) : (
                    'Upload to YouTube'
                  )}
                </Button>
              </Card>
            )}
          </div>
        )}
      </Card>
    </div>
  );
};

export default YouTubeAutomation;
